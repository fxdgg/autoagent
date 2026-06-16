#!/usr/bin/env python3
"""
autoagent-exec: Long-running task launcher for AutoAgent.

This script is called by the AI through a wrapper script (autoagent-exec.bat
on Windows, autoagent-exec.sh on Linux/macOS).  The wrapper pre-fills all
internal parameters (log directory, task ID, fast-fail timeout); the AI only
needs to append the command to run (wrapped in double quotes).

The command is passed as a single shell string via ``--cmd``, which means
shell operators (&&, |, ;, etc.) are preserved and executed correctly.
This makes autoagent-exec behave like a real terminal for the AI.

It implements a fast-fail mechanism (default 10 seconds, configurable via
config.yaml ``fast_fail_timeout``):
  - Start the command as a **detached process** (new session/process group)
  - Immediately write a "starting" signal file and launch a detached monitor
  - If the command exits within the timeout with a non-zero exit code, report
    the error immediately so the AI can fix the command without restarting
  - If it's still running after the timeout, update the signal file to
    "running" and tell the AI to end its session

The subprocess and monitor are detached at T=0 (new session on Unix,
DETACHED_PROCESS on Windows) so that even if the AI's Bash tool kills
autoagent-exec mid-wait, the subprocess and monitor survive.

Usage (via wrapper script):
    autoagent-exec.bat "<command...>"          (Windows)
    bash autoagent-exec.sh "<command...>"      (Linux/macOS)

Examples:
    autoagent-exec.bat "cd build && cmake .. && make -j8"
    autoagent-exec.bat "python train.py --epochs 100 | tee log.txt"

Internal invocation (by the wrapper script, not by the AI directly):
    python autoagent_exec.py --log-dir <dir> --task-id <id> [--fast-fail-timeout <s>] --cmd "<command>"

Signal file: <log-dir>/lr_tasks/lr_<task_id>_signal.json
Output log:  <log-dir>/lr_tasks/lr_<task_id>_output.log
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

# Default timeout in seconds for fast-fail detection.
# Can be overridden via --fast-fail-timeout CLI argument,
# which is configured in config.yaml as fast_fail_timeout.
DEFAULT_FAST_FAIL_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Defensive redirection detection
# ---------------------------------------------------------------------------

_REDIRECT_PATTERNS = [
    # &>> file, &> file  (bash: redirect both stdout+stderr)
    r'(?P<both1_op>&>>?)\s*(?P<both1_path>\S+)',
    # 2>&1 > file  or  2>&1 >> file
    r'(?P<both2_op>2>&1\s*>>?)\s*(?P<both2_path>\S+)',
    # 2>&1  (fd merge, no file path — just discard the operator)
    r'(?P<merge_op>2>&1)',
    # 2>> file, 2> file
    r'(?P<err_op>2>>?)\s*(?P<err_path>\S+)',
    # >> file, > file  (but not 2> or &>)
    r'(?<![12&])(?P<out_op>>>?)\s*(?P<out_path>\S+)',
    # | tee [-a] file
    r'(?P<tee_op>\|\s*tee)(?:\s+-a)?\s+(?P<tee_path>\S+)',
]
_REDIRECT_RE = re.compile(
    r'(?:' + '|'.join(_REDIRECT_PATTERNS) + r')\s*$',
    re.IGNORECASE,
)


class _RedirectInfo:
    """Result of :func:`_strip_redirections`.

    Attributes:
        command:     The command string with trailing redirection removed.
        stdout_path: Extracted stdout redirect target, or ``None``.
        stderr_path: Extracted stderr redirect target, or ``None``.
        stripped:    ``True`` if any redirection was actually removed.
    """
    __slots__ = ('command', 'stdout_path', 'stderr_path', 'stripped')

    def __init__(self, command: str, stdout_path: 'str | None',
                 stderr_path: 'str | None', stripped: bool):
        self.command = command
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path
        self.stripped = stripped


def _strip_redirections(command_str: str) -> _RedirectInfo:
    """Detect and strip trailing output redirection from *command_str*.

    This is a best-effort, **iterative** scan that repeatedly removes the
    last trailing redirection operator until none remain.  Complex
    mid-command piping (e.g. ``cmd1 > a.log | cmd2``) is intentionally
    NOT touched — only redirections anchored at the end of the command
    are handled.

    Returns a :class:`_RedirectInfo` with the cleaned command and the
    extracted file paths (if any).
    """
    stdout_path: 'str | None' = None
    stderr_path: 'str | None' = None
    ever_stripped = False
    cleaned = command_str

    # Iteratively strip trailing redirections from right to left.
    while True:
        m = _REDIRECT_RE.search(cleaned)
        if not m:
            break
        ever_stripped = True
        cleaned = cleaned[:m.start()].rstrip()

        # Classify which stream(s) were redirected.
        if m.group('both1_op') is not None:
            target = m.group('both1_path')
            if stdout_path is None:
                stdout_path = target
            if stderr_path is None:
                stderr_path = target
        elif m.group('both2_op') is not None:
            target = m.group('both2_path')
            if stdout_path is None:
                stdout_path = target
            if stderr_path is None:
                stderr_path = target
        elif m.group('merge_op') is not None:
            pass  # fd merge, no file path to extract
        elif m.group('err_op') is not None:
            if stderr_path is None:
                stderr_path = m.group('err_path')
        elif m.group('tee_op') is not None:
            if stdout_path is None:
                stdout_path = m.group('tee_path')
        else:
            # out_op: > or >>
            if stdout_path is None:
                stdout_path = m.group('out_path')

    if not ever_stripped:
        return _RedirectInfo(command_str, None, None, stripped=False)
    return _RedirectInfo(cleaned, stdout_path, stderr_path, stripped=True)


def _ensure_utf8_stdio():
    """Reconfigure stdout/stderr to UTF-8 to avoid GBK encoding errors on Windows."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)


def parse_args():
    parser = argparse.ArgumentParser(
        description="AutoAgent long-running task launcher.\n\n"
            "This script is invoked through the autoagent-exec wrapper script\n"
            "(autoagent-exec.bat on Windows, autoagent-exec.sh on Linux/macOS).\n"
            "All internal parameters (log directory, task ID, timeout, etc.) are\n"
            "pre-configured in the wrapper script — you only need to append the\n"
            "command you want to run.\n\n"
            "The wrapper script forwards your entire command line as a single\n"
            "shell string, so you can use shell features like cd, &&, |, ;, etc.\n"
            "just as you would in a real terminal.\n\n"
            "Usage (via wrapper script):\n"
            "  <path>/autoagent-exec.bat <command...>     (Windows)\n"
            "  bash <path>/autoagent-exec.sh <command...>  (Linux/macOS)\n\n"
            "Examples:\n"
            "  autoagent-exec.bat make -j8\n"
            "  autoagent-exec.bat cd build && cmake .. && make -j8\n"
            "  autoagent-exec.bat python train.py --epochs 100 | tee log.txt\n"
            "  bash autoagent-exec.sh ncu --set full ./main.exe\n\n"
            "Behavior:\n"
            "  - If the command fails quickly, the error is shown immediately\n"
            "    so you can fix and retry without restarting the session.\n"
            "  - If the command is still running after the fast-run window,\n"
            "    it is detached to the background. You should then end your\n"
            "    session; AutoAgent will call you back when it completes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        usage="autoagent-exec.bat <command...>  OR  bash autoagent-exec.sh <command...>",
    )
    # Internal parameters — hidden from --help because they are pre-filled
    # by the wrapper script. AI should never set these manually.
    parser.add_argument(
        "--log-dir",
        required=True,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--task-id",
        required=True,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--fast-fail-timeout",
        type=int,
        default=DEFAULT_FAST_FAIL_TIMEOUT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--show-console",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--cmd",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--stdout",
        default=None,
        help=(
            "Copy captured stdout to this file path. "
            "Use this instead of adding > redirection to the command."
        ),
    )
    parser.add_argument(
        "--stderr",
        default=None,
        help=(
            "Copy captured stderr to this file path. "
            "Use this instead of adding 2> redirection to the command."
        ),
    )
    # Positional argument: the command string to execute.
    # When invoked via the wrapper script (without --cmd), the command
    # arrives as one or more positional arguments.
    parser.add_argument(
        "command",
        nargs="*",
        help='The command to run (wrap in double quotes).',
    )
    args = parser.parse_args()

    # Resolve command: --cmd takes precedence (backward compat),
    # otherwise join positional arguments.
    if args.cmd:
        args.command_str = args.cmd
    elif args.command:
        args.command_str = " ".join(args.command)
    else:
        parser.error(
            "No command specified. Usage: autoagent-exec \"<command>\""
        )

    return args


def write_signal_file(path: str, data: dict):
    """Write or update the signal file atomically."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    # os.replace works on all platforms in Python 3.3+ and handles
    # both existing and non-existing targets atomically.
    os.replace(tmp_path, path)


def _start_monitor(pid: int, signal_file: str, output_log: str,
                   fast_fail_timeout: int = 0):
    """Launch a detached monitor process.

    The monitor waits for the subprocess (by *pid*) to exit, then updates
    the signal file to ``finished`` or ``error``.

    If *fast_fail_timeout* > 0, the monitor will also update the signal
    from ``starting`` to ``running`` after that many seconds — but only
    if autoagent-exec hasn't already done so (i.e. the signal is still
    ``starting``, meaning autoagent-exec was killed by the AI's Bash
    tool timeout before it could update the signal itself).
    """
    monitor_cmd = [
        sys.executable, __file__,
        "--monitor",
        "--pid", str(pid),
        "--signal-file", signal_file,
        "--output-log", output_log,
        "--fast-fail-timeout", str(fast_fail_timeout),
    ]
    monitor_kwargs = {}
    if os.name == "nt":
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


def main():
    args = parse_args()

    log_dir = args.log_dir
    task_id = args.task_id
    command_str = args.command_str
    fast_fail_timeout = args.fast_fail_timeout

    # Ensure lr_tasks subdirectory exists
    lr_tasks_dir = os.path.join(log_dir, "lr_tasks")
    os.makedirs(lr_tasks_dir, exist_ok=True)

    # File paths (all lr_ files go into the lr_tasks subdirectory)
    signal_file = os.path.join(lr_tasks_dir, f"lr_{task_id}_signal.json")
    output_log = os.path.join(lr_tasks_dir, f"lr_{task_id}_output.log")

    # ── Guard + Acquire: atomic check-and-lock via signal file ──
    # We merge the concurrency guard and the initial signal write into
    # one step so there is no window between "check passed" and "signal
    # written" where a parallel invocation could slip through.
    #
    # Strategy: try to atomically create a .lock file (O_CREAT|O_EXCL).
    # If it already exists, another autoagent-exec is in the middle of
    # starting — treat that as a concurrent collision.  After we win the
    # race we check the *existing* signal file for starting/running
    # status (the normal guard), then overwrite it with our "starting"
    # signal.
    _lock_path = signal_file + ".lock"
    try:
        _lock_fd = os.open(_lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(_lock_fd)
    except FileExistsError:
        # Another autoagent-exec is writing right now — reject.
        print(
            f"[ERROR] Another autoagent-exec instance is starting for task-id '{task_id}'.\n"
            f"   It is not allowed to have two long-running tasks in parallel.\n"
            f"   Wait for the current autoagent-exec task to finish before launching another.",
            file=sys.stderr,
        )
        sys.exit(1)

    # We hold the lock (.lock exists, created by us).  Now check the
    # existing signal file for an already-active task.
    try:
        if os.path.isfile(signal_file):
            try:
                with open(signal_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("status") in ("starting", "running"):
                    existing_pid = existing.get("pid", "?")
                    existing_cmd = existing.get("command", "?")
                    print(
                        f"[ERROR] A long-running task is already active for task-id '{task_id}'.\n"
                        f"   Existing PID: {existing_pid}\n"
                        f"   Existing command: {existing_cmd}\n"
                        f"\n"
                        f"   It is not allowed to have two long-running tasks in parallel.\n"
                        f"   Wait for the current autoagent-exec task to finish before launching another.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            except (json.JSONDecodeError, OSError):
                pass  # Corrupted or unreadable — proceed normally

        # Clear the default output log for every accepted launch.
        try:
            with open(output_log, "wb"):
                pass
        except OSError as e:
            print(
                f"[ERROR] Failed to clear output log for task-id '{task_id}': {e}",
                file=sys.stderr,
            )
            sys.exit(1)

        # Write the "starting" signal (PID unknown yet — filled in after Popen).
        signal_data = {
            "task_id": task_id,
            "command": command_str,
            "pid": None,
            "output_log": output_log,
            "status": "starting",
            "description": (
                f"Acquiring task slot. Subprocess not yet started."
            ),
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "finished_at": None,
            "exit_code": None,
        }
        write_signal_file(signal_file, signal_data)
    finally:
        # Release the lock — remove the .lock file so future
        # invocations can proceed normally.
        try:
            os.remove(_lock_path)
        except OSError:
            pass

    # ── Defensive check: strip redirection and auto-fill --stdout/--stderr ──
    redir = _strip_redirections(command_str)
    if redir.stripped:
        print(
            f"[autoagent-exec] Detected output redirection in command — "
            f"stripping it automatically."
        )
        print(f"   Original command: {command_str}")
        print(f"   Cleaned command:  {redir.command}")
        if redir.stdout_path:
            print(f"   Extracted stdout target: {redir.stdout_path}")
        if redir.stderr_path:
            print(f"   Extracted stderr target: {redir.stderr_path}")
        sys.stdout.flush()

        # Use the cleaned command from now on.
        command_str = redir.command

        # Auto-fill --stdout / --stderr only when the user (AI) did not
        # already specify them via CLI flags.
        if redir.stdout_path and not args.stdout:
            args.stdout = redir.stdout_path
        if redir.stderr_path and not args.stderr:
            args.stderr = redir.stderr_path

    # ── Resolve stdout / stderr targets ──
    stdout_path = args.stdout  # may be None
    stderr_path = args.stderr  # may be None

    if stdout_path:
        _dir = os.path.dirname(stdout_path)
        if _dir:
            os.makedirs(_dir, exist_ok=True)
        stdout_fh = open(stdout_path, "wb")
    else:
        stdout_fh = open(output_log, "wb")

    if stderr_path:
        _dir = os.path.dirname(stderr_path)
        if _dir:
            os.makedirs(_dir, exist_ok=True)
        stderr_fh = open(stderr_path, "wb")
    else:
        # No explicit stderr target → merge into stdout's file
        stderr_fh = subprocess.STDOUT

    # Compute the effective output paths for display/signal purposes
    effective_stdout = stdout_path or output_log
    effective_stderr = stderr_path or effective_stdout  # merged when not split

    # Start the command in a new process group / session so that it
    # survives even if autoagent-exec is killed by the AI's Bash tool
    # timeout before the fast-fail window elapses.
    #
    # Windows: CREATE_NEW_PROCESS_GROUP alone is sufficient — it puts
    #   the subprocess in a separate process group so that a Ctrl+C /
    #   GenerateConsoleCtrlEvent on autoagent-exec won't propagate.
    #   When --show-console is set, DETACHED_PROCESS is added so the
    #   subprocess gets its own visible console window (useful for
    #   debugging).  Without --show-console we omit it to avoid
    #   surprise pop-up windows.
    # Unix: start_new_session=True (setsid) creates a new session,
    #   making the subprocess immune to signals sent to the parent's
    #   process group.
    show_console = args.show_console
    try:
        kwargs = {}
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP
            if show_console:
                flags |= subprocess.DETACHED_PROCESS
            kwargs["creationflags"] = flags
        else:
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            command_str,
            shell=True,
            stdout=stdout_fh,
            stderr=stderr_fh,
            stdin=subprocess.DEVNULL,
            cwd=os.getcwd(),
            **kwargs,
        )
    except Exception as e:
        print(f"[ERROR] Failed to start command: {e}", file=sys.stderr)
        print(f"   Command: {command_str}", file=sys.stderr)
        stdout_fh.close()
        if stderr_fh not in (subprocess.STDOUT, stdout_fh):
            stderr_fh.close()
        # Clean up the signal file so a retry is not blocked.
        signal_data = {
            "task_id": task_id,
            "command": command_str,
            "pid": None,
            "output_log": output_log,
            "stdout_log": effective_stdout,
            "stderr_log": effective_stderr,
            "status": "error",
            "description": f"Failed to start command: {e}",
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "exit_code": None,
        }
        write_signal_file(signal_file, signal_data)
        sys.exit(1)

    pid = proc.pid

    # ── Update signal with real PID ──
    # The signal file was written with pid=None before Popen.
    # Now fill in the PID and update description.
    signal_data = {
        "task_id": task_id,
        "command": command_str,
        "pid": pid,
        "output_log": output_log,
        "stdout_log": effective_stdout,
        "stderr_log": effective_stderr,
        "status": "starting",
        "description": (
            f"Process started (PID {pid}). "
            f"Watching for {fast_fail_timeout}s to detect fast failures."
        ),
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "finished_at": None,
        "exit_code": None,
    }
    write_signal_file(signal_file, signal_data)

    # ── Start detached monitor immediately ──
    # The monitor will: (1) update starting→running after fast_fail_timeout
    # if autoagent-exec was killed, (2) wait for process exit, (3) update
    # signal to finished/error.
    _start_monitor(pid, signal_file, output_log,
                   fast_fail_timeout=fast_fail_timeout)

    # ── Print STARTING info immediately ──
    # This output is visible even if the AI's Bash tool kills us early.
    print(f"[autoagent-exec] STARTING (PID {pid})")
    print(f"   Command: {command_str}")
    print(f"   Do NOT launch another autoagent-exec until this task finishes.")
    sys.stdout.flush()

    # --- Fast-fail phase: wait up to fast_fail_timeout seconds ---
    try:
        exit_code = proc.wait(timeout=fast_fail_timeout)
    except subprocess.TimeoutExpired:
        exit_code = None  # Still running after timeout

    if exit_code is not None:
        # Process exited within the timeout
        stdout_fh.close()
        if stderr_fh not in (subprocess.STDOUT, stdout_fh):
            stderr_fh.close()

        if exit_code == 0:
            # Command finished successfully (it was fast, not really long-running)
            print(f"\n[OK] Command finished quickly (exit code 0).")
            _print_output_smart(effective_stdout)

            signal_data = {
                "task_id": task_id,
                "command": command_str,
                "pid": pid,
                "output_log": output_log,
                "stdout_log": effective_stdout,
                "stderr_log": effective_stderr,
                "status": "finished",
                "description": "Command completed successfully.",
                "exit_code": 0,
                "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            write_signal_file(signal_file, signal_data)
            sys.exit(0)
        else:
            # Command failed fast — print error for AI to see and retry
            print(f"\n[FAST-FAIL] Command failed within {fast_fail_timeout}s (exit code {exit_code}).")
            _print_output_smart(effective_stdout)

            # Write error signal so the concurrency guard allows retry
            signal_data = {
                "task_id": task_id,
                "command": command_str,
                "pid": pid,
                "output_log": output_log,
                "stdout_log": effective_stdout,
                "stderr_log": effective_stderr,
                "status": "error",
                "description": f"Command failed quickly (exit code {exit_code}).",
                "exit_code": exit_code,
                "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            write_signal_file(signal_file, signal_data)
            sys.exit(exit_code)

    # --- Command is still running after fast_fail_timeout seconds ---
    # Close our file handles so the subprocess owns the only handles to
    # the log files.  On Windows this avoids sharing-violation issues.
    stdout_fh.close()
    if stderr_fh not in (subprocess.STDOUT, stdout_fh):
        stderr_fh.close()

    print(f"\n[RUNNING] Command is still running after {fast_fail_timeout}s -- treating as long-running task.")

    # Update signal file to "running"
    signal_data = {
        "task_id": task_id,
        "command": command_str,
        "pid": pid,
        "output_log": output_log,
        "stdout_log": effective_stdout,
        "stderr_log": effective_stderr,
        "status": "running",
        "description": f"Command still running after {fast_fail_timeout}s. Monitoring in background.",
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "finished_at": None,
        "exit_code": None,
    }
    write_signal_file(signal_file, signal_data)

    # Monitor was already started at T=0 — no need to start it again.

    print(f"\n" + "=" * 60)
    print(f"  TASK SUBMITTED")
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

    If --fast-fail-timeout is provided, the monitor first sleeps for that
    duration and then promotes the signal from "starting" to "running" —
    but only if autoagent-exec hasn't already done so (i.e. it was killed
    by the AI's Bash tool before it could update the signal itself).
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--signal-file", required=True)
    parser.add_argument("--output-log", required=True)
    parser.add_argument("--fast-fail-timeout", type=int, default=0)
    args = parser.parse_args()

    pid = args.pid
    signal_file = args.signal_file
    fast_fail_timeout = args.fast_fail_timeout

    # ── Step 1: Wait for fast-fail window, then promote starting → running ──
    # If autoagent-exec is still alive, it will update the signal itself.
    # We only intervene if the signal is still "starting" (meaning
    # autoagent-exec was killed before it could update).
    if fast_fail_timeout > 0:
        time.sleep(fast_fail_timeout)
        try:
            with open(signal_file, "r", encoding="utf-8") as f:
                sig = json.load(f)
            if sig.get("status") == "starting":
                sig["status"] = "running"
                sig["description"] = (
                    f"Command still running after {fast_fail_timeout}s. "
                    f"Monitoring in background."
                )
                write_signal_file(signal_file, sig)
        except Exception:
            pass  # Best-effort; signal file may have been updated already

    # ── Step 2: Wait for the process to exit ──
    exit_code = _wait_for_process(pid)

    # ── Step 3: Update signal file with final status ──
    try:
        with open(signal_file, "r", encoding="utf-8") as f:
            signal_data = json.load(f)
    except Exception:
        signal_data = {}

    if exit_code is None:
        signal_data["status"] = "finished"
        signal_data.pop("exit_code", None)
        signal_data["description"] = "Process exited (exit code unavailable)."
        signal_data["note"] = "Process exited but exit code unavailable (platform limitation)"
    else:
        signal_data["status"] = "finished" if exit_code == 0 else "error"
        signal_data["exit_code"] = exit_code
        signal_data["description"] = (
            "Command completed successfully." if exit_code == 0
            else f"Command failed (exit code {exit_code})."
        )

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


# Maximum output length (in characters) to print inline.
# If the output exceeds this, only the log file path is shown.
_INLINE_OUTPUT_MAX_CHARS = 3000


def _print_output_smart(output_log: str):
    """Print command output inline if short, or show the log path if long.

    - If the output is empty, prints a note saying no output was captured.
    - If the output length <= _INLINE_OUTPUT_MAX_CHARS, prints the full
      content inline with an explicit note that it is NOT truncated, so the
      AI does not attempt to read the file again.
    - If the output is longer, only prints the log file path so the AI can
      read it if needed.
    """
    try:
        content = _read_log_file(output_log)
    except Exception as e:
        print(f"   (failed to read output log: {e})")
        return

    stripped = content.strip()
    if not stripped:
        print(f"   (no output captured)")
        return

    if len(stripped) <= _INLINE_OUTPUT_MAX_CHARS:
        print(f"\n--- Command Output (complete, not truncated) ---")
        print(stripped)
        print(f"--- End of Output ---")
    else:
        print(f"   Output is too long ({len(stripped)} chars) to display inline.")
        print(f"   Full output log: {output_log}")


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
