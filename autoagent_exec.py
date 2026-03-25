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
import subprocess
import sys
import time
import threading
import signal as signal_mod


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
        description="AutoAgent long-running task launcher",
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
    # Atomic rename (works on Windows for replacing existing files in Python 3.3+)
    if os.path.exists(path):
        os.replace(tmp_path, path)
    else:
        os.rename(tmp_path, path)


def monitor_process(proc: subprocess.Popen, signal_file: str, output_log: str):
    """
    Monitor the background process and update the signal file when it finishes.
    
    This function runs in a daemon-like manner after the main script has
    printed the "task submitted" message.
    """
    # Wait for process to complete
    proc.wait()

    exit_code = proc.returncode
    status = "finished" if exit_code == 0 else "error"

    # Update signal file
    try:
        with open(signal_file, "r", encoding="utf-8") as f:
            signal_data = json.load(f)
    except Exception:
        signal_data = {}

    signal_data["status"] = status
    signal_data["exit_code"] = exit_code
    signal_data["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    write_signal_file(signal_file, signal_data)


def main():
    args = parse_args()

    log_dir = args.log_dir
    task_id = args.task_id
    command = args.command
    command_str = " ".join(command)

    # Ensure lr_tasks subdirectory exists
    lr_tasks_dir = os.path.join(log_dir, "lr_tasks")
    os.makedirs(lr_tasks_dir, exist_ok=True)

    # File paths (all lr_ files go into the lr_tasks subdirectory)
    signal_file = os.path.join(lr_tasks_dir, f"lr_{task_id}_signal.json")
    output_log = os.path.join(lr_tasks_dir, f"lr_{task_id}_output.log")

    # Open output log file
    log_fh = open(output_log, "w", encoding="utf-8", errors="replace")

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
                with open(output_log, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if content.strip():
                    # Show last 3000 chars
                    tail = content[-3000:] if len(content) > 3000 else content
                    print(f"\n--- Command Output (last part) ---")
                    print(tail)
                    print(f"--- End of Output ---")
                else:
                    print(f"   (no output captured)")
            except Exception:
                pass

            # Do NOT write a signal file — let the AI fix and retry
            sys.exit(exit_code)

    # --- Command is still running after FAST_FAIL_TIMEOUT seconds ---
    # Detach: we don't need to do anything special since stdout/stderr
    # are already redirected to the log file. The process will continue
    # running even after this script exits.

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

    # Start a background monitoring thread that will update the signal file
    # when the process finishes. This thread is a daemon thread, so if
    # this script is killed, the background process still runs independently.
    monitor_thread = threading.Thread(
        target=monitor_process,
        args=(proc, signal_file, output_log),
        daemon=False,  # Non-daemon so it keeps running
    )
    monitor_thread.start()

    print(f"\n" + "=" * 60)
    print(f"  LONG-RUNNING TASK SUBMITTED SUCCESSFULLY")
    print(f"  The task is running in the background.")
    print(f"  You MUST now end your current session immediately.")
    print(f"  Output your final status as: LONG_RUNNING_IN_PROGRESS")
    print(f"  AutoAgent will call you back when the task completes.")
    print(f"=" * 60)

    # Wait for the monitor thread to complete (i.e., wait for the process)
    # This keeps the script alive to update the signal file.
    # The AI's Bash tool will see the output above and should end the session.
    monitor_thread.join()


if __name__ == "__main__":
    _ensure_utf8_stdio()
    main()
