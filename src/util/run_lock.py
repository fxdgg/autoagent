"""Cross-process run locks for AutoAgent execution targets."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import signal
import sys
import tempfile
import time
import uuid
from typing import Any, Optional, Tuple


class RunLockError(RuntimeError):
    """Raised when an execution target is already locked by another process."""


def canonicalize_target_path(path: str) -> str:
    """Return a stable path identity for lock hashing and comparison.

    We deliberately avoid ``os.path.realpath`` here: on Windows, junctions
    and symlinks can produce surprising results, and our goal is only to
    compare the *path the user provided* across processes. Two callers
    that pass the same absolute path should always agree on the lock
    identity, regardless of any filesystem links along the way.
    """
    absolute = os.path.abspath(path)
    return os.path.normcase(os.path.normpath(absolute))


def _default_lock_dir() -> str:
    """System-wide lock directory shared by all AutoAgent processes.

    Using ``tempfile.gettempdir()`` ensures that two AutoAgent invocations
    targeting the same config file collide on the same lock file even
    when they were started from different working directories or with
    different ``--log-dir`` values.
    """
    return os.path.join(tempfile.gettempdir(), "autoagent-locks")


# ───────────────────────── Process liveness / identity ─────────────────────────

def _get_process_start_time(pid: int) -> Optional[str]:
    """Return a stable, opaque start-time token for ``pid`` or ``None``.

    The exact format does not matter; only equality comparison does. We
    return ``None`` on any failure so callers can fall back to a plain
    PID-only check.
    """
    if pid <= 0:
        return None

    if os.name == "nt":
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            process_query_limited_information = 0x1000
            handle = kernel32.OpenProcess(
                process_query_limited_information, False, int(pid)
            )
            if not handle:
                return None
            try:
                # FILETIME structs: creation, exit, kernel, user
                creation = ctypes.c_ulonglong(0)
                exit_ = ctypes.c_ulonglong(0)
                kernel = ctypes.c_ulonglong(0)
                user = ctypes.c_ulonglong(0)
                ok = kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                )
                if not ok:
                    return None
                return f"win:{creation.value}"
            finally:
                kernel32.CloseHandle(handle)
        except OSError:
            return None

    # Linux / *nix: read /proc/<pid>/stat field 22 (starttime, in clock ticks).
    proc_stat = f"/proc/{pid}/stat"
    if os.path.exists(proc_stat):
        try:
            with open(proc_stat, "r", encoding="utf-8") as f:
                content = f.read()
            # The 2nd field (comm) is parenthesised and may contain spaces;
            # split on the last ')' to skip it safely.
            rparen = content.rfind(")")
            if rparen == -1:
                return None
            tail = content[rparen + 1:].split()
            # tail[0] is field 3 (state); starttime is field 22 → tail index 19.
            if len(tail) >= 20:
                return f"linux:{tail[19]}"
            return None
        except OSError:
            return None

    return None


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True

    if os.name == "nt":
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            process_query_limited_information = 0x1000
            handle = kernel32.OpenProcess(
                process_query_limited_information, False, int(pid)
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except OSError:
            return False

    proc_status = f"/proc/{pid}/status"
    if os.path.exists(proc_status):
        try:
            with open(proc_status, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("State:"):
                        return "Z" not in line
            return True
        except OSError:
            return False

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _is_owner_alive(pid: int, recorded_start_time: Optional[str]) -> bool:
    """Liveness check that is robust against PID reuse.

    If a recorded start time exists, the live process must match it. If
    we can't determine a start time on either side, fall back to a
    plain PID-only liveness check (best-effort, identical to the old
    behaviour).
    """
    if not _is_pid_alive(pid):
        return False
    if not recorded_start_time:
        return True
    current = _get_process_start_time(pid)
    if current is None:
        # Couldn't read it now; don't punish a live process for that.
        return True
    return current == recorded_start_time


# ───────────────────────────────── RunLock ─────────────────────────────────

class RunLock:
    """A zero-dependency lock for one AutoAgent execution target.

    The lock is represented by one atomically-created JSON file under a
    fixed system-wide directory (``<tempdir>/autoagent-locks``). A live
    PID with matching start time blocks other processes; a dead PID
    or a mismatching start time is treated as stale and reclaimed.
    """

    def __init__(
        self,
        target_type: str,
        target_path: str,
        owner_id: Optional[str] = None,
        session_id: str = "",
        lock_dir: Optional[str] = None,
    ):
        self.target_type = target_type
        self.target_path = os.path.abspath(target_path)
        self.canonical_path = canonicalize_target_path(target_path)
        self.owner_id = owner_id or f"{os.getpid()}-{uuid.uuid4().hex}"
        self.session_id = session_id
        self.pid = os.getpid()
        self.start_time = _get_process_start_time(self.pid)
        self.lock_dir = os.path.abspath(lock_dir) if lock_dir else _default_lock_dir()
        self.lock_path = self._build_lock_path()
        self._acquired = False
        self._previous_handlers: dict = {}

    def _build_lock_path(self) -> str:
        digest = hashlib.sha256(self.canonical_path.encode("utf-8")).hexdigest()[:24]
        return os.path.join(self.lock_dir, f"{self.target_type}_{digest}.lock")

    def _payload(self) -> dict:
        return {
            "owner_id": self.owner_id,
            "pid": self.pid,
            "start_time": self.start_time,
            "session_id": self.session_id,
            "target_type": self.target_type,
            "target_path": self.target_path,
            "canonical_path": self.canonical_path,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _write_payload_to_fd(self, fd: int) -> None:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self._payload(), f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

    def _rewrite_payload(self) -> None:
        tmp_path = f"{self.lock_path}.{self.pid}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._payload(), f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.lock_path)

    def _read_existing_lock(self) -> dict:
        last_error: Optional[Exception] = None
        for _ in range(3):
            try:
                with open(self.lock_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError) as e:
                last_error = e
                time.sleep(0.05)
        raise RunLockError(
            f"Cannot read lock file for {self.target_type}: {self.lock_path}. "
            f"Remove it manually if no AutoAgent process is running. "
            f"Read error: {last_error}"
        )

    def acquire(self) -> "RunLock":
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)

        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                existing = self._read_existing_lock()
                existing_pid = int(existing.get("pid") or -1)
                existing_start = existing.get("start_time")
                if existing_pid > 0 and not _is_owner_alive(existing_pid, existing_start):
                    try:
                        os.remove(self.lock_path)
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        raise RunLockError(
                            f"Stale lock for {self.target_type} could not be removed: "
                            f"{self.lock_path}. Error: {e}"
                        ) from e
                    continue

                session = existing.get("session_id") or "(unknown session)"
                target = existing.get("target_path") or self.target_path
                raise RunLockError(
                    f"Another AutoAgent process is already using this "
                    f"{self.target_type}: {target}\n"
                    f"Owner PID: {existing_pid if existing_pid > 0 else 'unknown'}\n"
                    f"Owner session: {session}\n"
                    f"Lock file: {self.lock_path}"
                )
            else:
                try:
                    self._write_payload_to_fd(fd)
                except Exception:
                    try:
                        os.remove(self.lock_path)
                    except OSError:
                        pass
                    raise
                self._acquired = True
                self._install_signal_handlers()
                return self

    def update_session_id(self, session_id: str) -> None:
        self.session_id = session_id
        if self._acquired:
            self._rewrite_payload()

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            existing = self._read_existing_lock()
            if (
                existing.get("owner_id") == self.owner_id
                and int(existing.get("pid") or -1) == self.pid
            ):
                os.remove(self.lock_path)
        except (FileNotFoundError, OSError, RunLockError):
            pass
        finally:
            self._acquired = False
            self._restore_signal_handlers()

    # ───────────── Signal handling ─────────────

    def _install_signal_handlers(self) -> None:
        """Register SIGINT/SIGTERM handlers that release the lock first.

        We only install handlers in the main thread (signal.signal()
        rejects calls from non-main threads). Previously installed
        handlers are saved and restored on release().
        """
        try:
            import threading
            if threading.current_thread() is not threading.main_thread():
                return
        except Exception:
            return

        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                previous = signal.getsignal(sig)
            except (ValueError, OSError):
                continue
            if sig in self._previous_handlers:
                # Already installed once; don't overwrite the saved previous.
                continue
            self._previous_handlers[sig] = previous

            def _handler(signum: int, frame: Any, _sig_name: str = sig_name) -> None:
                # Release the lock as soon as possible.
                try:
                    self.release()
                except Exception:
                    pass
                # Re-raise the conventional behaviour for this signal.
                if _sig_name == "SIGINT":
                    raise KeyboardInterrupt()
                # SIGTERM (and any other registered signal) → exit code 128+signum.
                sys.exit(128 + int(signum))

            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                # E.g. on Windows SIGTERM may be limited; ignore quietly.
                self._previous_handlers.pop(sig, None)

    def _restore_signal_handlers(self) -> None:
        for sig, previous in list(self._previous_handlers.items()):
            try:
                signal.signal(sig, previous)
            except (ValueError, OSError, TypeError):
                pass
        self._previous_handlers.clear()

    # ───────────── Context manager ─────────────

    def __enter__(self) -> "RunLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
