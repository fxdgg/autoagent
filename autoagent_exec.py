#!/usr/bin/env python3
"""
autoagent-exec: Long-running task launcher for AutoAgent.

This script is called by the AI (via Bash tool) to submit a long-running task.
It implements a "10-second fast-fail" mechanism:
  - Start the command in foreground
  - If it exits within 10 seconds with a non-zero exit code, report the error
    immediately so the AI can fix the command without restarting the session
  - If it's still running after 10 seconds, detach it to the background,
    write a signal file, and tell the AI to end its session

Usage (called by AI via Bash):
    python <path>/autoagent_exec.py --log-dir <log_session_dir> --task-id <id> -- <command...>

Example:
    python autoagent_exec.py --log-dir /path/to/logs/proj_abc123 --task-id 1.2 -- ncu --set full --csv ./build/Release/main.exe

Signal file: <log-dir>/lr_tasks/lr_<task_id>_signal.json
Output log:  <log-dir>/lr_tasks/lr_<task_id>_output.log
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time

# Timeout in seconds for fast-fail detection
FAST_FAIL_TIMEOUT = 10


def _ensure_utf8_stdio():
    """Reconfigure stdout/stderr to UTF-8 to avoid GBK encoding errors on Windows."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)


def parse_args():
    parser = argparse.ArgumentParser(
        description="AutoAgent long-running task launcher.\n\n"
            "Runs a command with fast-fail detection:\n"
            "  - If the command exits within 10s with an error, the error is shown immediately.\n"
            "  - If the command is still running after 10s, it is detached to the background\n"
            "    and a signal file is created for the orchestrator to monitor.\n\n"
            "Examples:\n"
            "  python autoagent_exec.py --log-dir /path/to/logs --task-id 1.2 -- make -j8\n"
            "  python autoagent_exec.py --log-dir /path/to/logs --task-id 2.1 -- python train.py --epochs 100\n"
            "  python autoagent_exec.py --log-dir /path/to/logs --task-id 1.3 -- ncu --set full ./main.exe\n\n"
            "Output files (created under <log-dir>/lr_tasks/):\n"
            "  lr_<task-id>_signal.json  - Status signal file (running/finished/error)\n"
            "  lr_<task-id>_output.log   - Full stdout+stderr output of the command",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        usage="autoagent_exec.py --log-dir <dir> --task-id <id> -- <command...>",
    )
    parser.add_argument(
        "--log-dir",
        required=True,
        help="Log session directory (absolute path) where signal and output files are written",
    )
    parser.add_argument(
        "--task-id",
        required=True,
        help="Subtask ID (e.g. 1.2)",
    )
    # Everything after '--' is the command
    args, remaining = parser.parse_known_args()

    # Remove leading '--' if present
    if remaining and remaining[0] == "--":
        remaining = remaining[1:]

    if not remaining:
        parser.error("No command specified. Usage: autoagent_exec.py --log-dir <dir> --task-id <id> -- <command...>")

    args.command = remaining
    return args


def write_signal_file(path: str, data: dict):
    """Write or update the signal file atomically."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    # os.replace works on all platforms in Python 3.3+ and handles
    # both existing and non-existing targets atomically.
    os.replace(tmp_path, path)


def main():
    args = parse_args()

    log_dir = args.log_dir
    task_id = args.task_id
    command = args.command
    # Re-quote the command list into a single shell string.
    # On Windows, use subprocess.list2cmdline (handles "C:/Program Files/...").
    # On POSIX, use shlex.join which produces /bin/sh-compatible quoting.
    if os.name == "nt":
        command_str = subprocess.list2cmdline(command)
    else:
        command_str = shlex.join(command)

    # Ensure lr_tasks subdirectory exists
    lr_tasks_dir = os.path.join(log_dir, "lr_tasks")
    os.makedirs(lr_tasks_dir, exist_ok=True)

    # File paths (all lr_ files go into the lr_tasks subdirectory)
    signal_file = os.path.join(lr_tasks_dir, f"lr_{task_id}_signal.json")
    output_log = os.path.join(lr_tasks_dir, f"lr_{task_id}_output.log")

    # Open output log file in binary mode so that the subprocess's raw
    # bytes (which may be GBK on Chinese Windows) are preserved as-is.
    # We will decode properly when reading the file back.
    log_fh = open(output_log, "wb")

    # Start the command
    try:
        # On Windows, use CREATE_NEW_PROCESS_GROUP so we can detach later
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            command_str,
            shell=True,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            cwd=os.getcwd(),
            **kwargs,
        )
    except Exception as e:
        print(f"[ERROR] Failed to start command: {e}", file=sys.stderr)
        print(f"   Command: {command_str}", file=sys.stderr)
        log_fh.close()
        sys.exit(1)

    pid = proc.pid

    # --- Fast-fail phase: wait up to FAST_FAIL_TIMEOUT seconds ---
    print(f"[autoagent-exec] Starting command (watching for {FAST_FAIL_TIMEOUT}s)...")
    print(f"   Command: {command_str}")
    print(f"   PID: {pid}")

    try:
        exit_code = proc.wait(timeout=FAST_FAIL_TIMEOUT)
    except subprocess.TimeoutExpired:
        exit_code = None  # Still running after timeout

    if exit_code is not None:
        # Process exited within the timeout
        log_fh.close()

        if exit_code == 0:
            # Command finished successfully (it was fast, not really long-running)
            print(f"\n[OK] Command finished quickly (exit code 0).")
            print(f"   Output log: {output_log}")

            # Write a "finished" signal file
            signal_data = {
                "task_id": task_id,
                "command": command_str,
                "pid": pid,
                "output_log": output_log,
                "status": "finished",
                "exit_code": 0,
                "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            write_signal_file(signal_file, signal_data)
            sys.exit(0)
        else:
            # Command failed fast — print error for AI to see and retry
            print(f"\n[FAST-FAIL] Command failed within {FAST_FAIL_TIMEOUT}s (exit code {exit_code}).")
            print(f"   Output log: {output_log}")

            # Print the log content so AI can see the error
            try:
                content = _read_log_file(output_log)
                if content.strip():
                    # Show last 3000 chars
                    tail = content[-3000:] if len(content) > 3000 else content
                    print(f"\n--- Command Output (last part) ---")
                    print(tail)
                    print(f"--- End of Output ---")
                else:
                    print(f"   (no output captured)")
            except Exception as e:
                print(f"   (failed to read output log: {e})")

            # Do NOT write a signal file — let the AI fix and retry
            sys.exit(exit_code)

    # --- Command is still running after FAST_FAIL_TIMEOUT seconds ---
    # Detach: we don't need to do anything special since stdout/stderr
    # are already redirected to the log file. The process will continue
    # running even after this script exits.

    # Close our file handle so the subprocess owns the only handle to
    # the log file.  On Windows this avoids sharing-violation issues.
    # The subprocess will continue writing via its inherited fd.
    log_fh.close()

    print(f"\n[RUNNING] Command is still running after {FAST_FAIL_TIMEOUT}s -- treating as long-running task.")
    print(f"   PID: {pid}")
    print(f"   Output log: {output_log}")
    print(f"   Signal file: {signal_file}")

    # Write signal file with "running" status
    signal_data = {
        "task_id": task_id,
        "command": command_str,
        "pid": pid,
        "output_log": output_log,
        "status": "running",
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "finished_at": None,
        "exit_code": None,
    }
    write_signal_file(signal_file, signal_data)

    # Start a detached monitor process that will update the signal file
    # when the command finishes. This is a completely independent process
    # so that this script can exit immediately (allowing the AI's Bash tool
    # to see our output and end the session).
    monitor_cmd = [
        sys.executable, __file__,
        "--monitor",
        "--pid", str(pid),
        "--signal-file", signal_file,
        "--output-log", output_log,
    ]
    monitor_kwargs = {}
    if os.name == "nt":
        # DETACHED_PROCESS: don't inherit console, keep running after parent exits
        monitor_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        monitor_kwargs["start_new_session"] = True

    try:
        subprocess.Popen(
            monitor_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **monitor_kwargs,
        )
    except Exception as e:
        print(f"[WARNING] Failed to start monitor process: {e}")
        print(f"   Signal file may not be updated when the command finishes.")
        print(f"   The orchestrator will fall back to process-alive checks.")

    print(f"\n" + "=" * 60)
    print(f"  LONG-RUNNING TASK SUBMITTED SUCCESSFULLY")
    print(f"  The task is running in the background (PID {pid}).")
    print(f"  You MUST now end your current session immediately.")
    print(f"  Output your final status as: LONG_RUNNING_IN_PROGRESS")
    print(f"  AutoAgent will call you back when the task completes.")
    print(f"=" * 60)

    # Exit immediately so the AI's Bash tool sees our output
    sys.exit(0)


def monitor_mode():
    """
    Monitor mode: wait for a process (by PID) to exit, then update the signal file.

    This runs as a completely detached process so that the main autoagent_exec
    script can exit immediately after submitting the long-running task.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--signal-file", required=True)
    parser.add_argument("--output-log", required=True)
    args = parser.parse_args()

    pid = args.pid
    signal_file = args.signal_file

    # Wait for the process to exit using OS-level APIs (no external dependencies)
    exit_code = _wait_for_process(pid)

    # Update signal file
    try:
        with open(signal_file, "r", encoding="utf-8") as f:
            signal_data = json.load(f)
    except Exception:
        signal_data = {}

    # If we couldn't get exit_code, assume finished (the orchestrator
    # will check output to determine success/failure)
    if exit_code is None:
        signal_data["status"] = "finished"
        signal_data["exit_code"] = -1
        signal_data["note"] = "Process exited but exit code unknown"
    else:
        signal_data["status"] = "finished" if exit_code == 0 else "error"
        signal_data["exit_code"] = exit_code

    signal_data["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    write_signal_file(signal_file, signal_data)


def _wait_for_process(pid: int) -> 'int | None':
    """
    Wait for a process to exit and return its exit code.
    
    Uses OS-level APIs without external dependencies:
    - Windows: OpenProcess + WaitForSingleObject + GetExitCodeProcess
    - Unix: poll with os.kill(pid, 0)
    
    Returns the exit code, or None if it could not be determined.
    """
    if os.name == "nt":
        return _wait_for_process_windows(pid)
    else:
        return _wait_for_process_unix(pid)


def _wait_for_process_windows(pid: int) -> 'int | None':
    """Wait for a Windows process using Win32 API."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    PROCESS_SYNCHRONIZE = 0x00100000
    PROCESS_QUERY_INFORMATION = 0x0400
    INFINITE = 0xFFFFFFFF
    WAIT_OBJECT_0 = 0

    handle = kernel32.OpenProcess(
        PROCESS_SYNCHRONIZE | PROCESS_QUERY_INFORMATION, False, pid
    )
    if not handle:
        # Process may have already exited
        return None

    try:
        # Wait indefinitely for the process to exit
        result = kernel32.WaitForSingleObject(handle, INFINITE)
        if result != WAIT_OBJECT_0:
            return None

        # Get exit code
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return exit_code.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def _wait_for_process_unix(pid: int) -> 'int | None':
    """Wait for a Unix process by polling /proc status.

    Uses /proc/<pid>/status to detect zombie processes (State: Z),
    which os.kill(pid, 0) cannot distinguish from running processes.
    Falls back to os.kill if /proc is unavailable (e.g. macOS).
    """
    while True:
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("State:"):
                        if "Z" in line:  # zombie — process finished
                            return None
                        break
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            # /proc entry gone → process exited, or /proc not available
            break
        except OSError:
            # Fallback: try os.kill for platforms without /proc
            try:
                os.kill(pid, 0)
            except OSError:
                break
        time.sleep(2)
    return None  # Can't determine exit code from another process on Unix


def _is_monitor_mode():
    return "--monitor" in sys.argv


def _read_log_file(path: str) -> str:
    """Read a log file with smart encoding detection.

    The log file is written in binary mode (raw bytes from the subprocess),
    so we need to detect the encoding. Strategy:
      1. Try UTF-8 (strict) — works for most modern tools.
      2. Fall back to the system's default encoding (e.g. GBK on Chinese Windows).
      3. Last resort: latin-1 (never fails, 1:1 byte mapping).
    """
    with open(path, "rb") as f:
        raw = f.read()

    # Try UTF-8 first
    try:
        return raw.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        pass

    # Try system default encoding (e.g. 'gbk' on Chinese Windows)
    sys_enc = sys.getdefaultencoding()
    # Also try the console encoding on Windows
    console_enc = None
    if os.name == "nt":
        import locale
        console_enc = locale.getpreferredencoding(False)

    for enc in (sys_enc, console_enc):
        if enc and enc.lower() not in ("utf-8", "utf8"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, ValueError, LookupError):
                pass

    # Last resort: latin-1 never fails
    return raw.decode("latin-1")


if __name__ == "__main__":
    _ensure_utf8_stdio()
    if _is_monitor_mode():
        monitor_mode()
    else:
        main()
