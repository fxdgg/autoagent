#!/usr/bin/env python3
"""
AutoAgent Simulation Test Runner

Automated test runner for AutoAgent orchestrator simulation tests.
Runs each test using the TestProvider (mock AI), then verifies the
resulting todos_state.yaml against expected outcomes.

Test definitions are read from test_schema.json in the test root directory.

Usage:
    python run_test.py                        # Run all tests
    python run_test.py --test 5               # Run only test 5
    python run_test.py --test 5 --test 8      # Run tests 5 and 8
    python run_test.py --verbose              # Show orchestrator output
    python run_test.py --list                 # List all tests
    python run_test.py --test-root /path/to   # Override test root directory
"""

import os
import sys
import json
import re
import time
import shutil
import argparse
import subprocess


# =============================================================================
# Path Resolution
# =============================================================================

def get_script_dir():
    """Get the directory containing this script (autoagent/)."""
    return os.path.dirname(os.path.abspath(__file__))


def get_default_test_root():
    """Get the default test root directory based on this script's location.

    Default: <script_dir>/test/simulation_test/
    """
    return os.path.join(get_script_dir(), "test", "simulation_test")


def load_test_schema(test_root):
    """Load test case definitions from test_schema.json in the test root.

    Returns a list of test case dicts.
    """
    schema_path = os.path.join(test_root, "test_schema.json")
    if not os.path.isfile(schema_path):
        print(f"ERROR: test_schema.json not found at: {schema_path}")
        sys.exit(1)

    with open(schema_path, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    if not isinstance(test_cases, list) or len(test_cases) == 0:
        print(f"ERROR: test_schema.json must be a non-empty JSON array")
        sys.exit(1)

    return test_cases


# =============================================================================
# Helper Functions
# =============================================================================

def ensure_git_initialized(project_root):
    """Ensure the test project has a git repository."""
    result = subprocess.run(
        "git status --porcelain",
        shell=True, capture_output=True, text=True,
        cwd=project_root,
    )
    if result.returncode != 0:
        subprocess.run("git init", shell=True, cwd=project_root,
                        capture_output=True)
        subprocess.run("git add -A", shell=True, cwd=project_root,
                        capture_output=True)
        subprocess.run(
            'git commit -m "initial commit"',
            shell=True, cwd=project_root, capture_output=True,
        )


def reset_test(project_root, log_dir):
    """Reset a test project to clean state.

    1. Git checkout + clean to restore tracked files and remove untracked ones
    2. Remove the log session directory (from .autoagent_log marker)
    """
    # Git reset
    subprocess.run("git checkout -- .", shell=True, cwd=project_root,
                    capture_output=True)
    subprocess.run("git clean -fd", shell=True, cwd=project_root,
                    capture_output=True)

    # Clean log session
    marker = os.path.join(project_root, ".autoagent_log")
    if os.path.exists(marker):
        try:
            with open(marker, "r", encoding="utf-8") as f:
                subdir_name = f.read().strip()
        except Exception:
            subdir_name = ""

        if subdir_name:
            session_dir = os.path.join(log_dir, subdir_name)
            if os.path.exists(session_dir):
                try:
                    shutil.rmtree(session_dir)
                except OSError as e:
                    print(f"warning: failed to remove previous session dir {session_dir}: {e}")

        try:
            os.remove(marker)
        except OSError:
            try:
                with open(marker, "w", encoding="utf-8") as f:
                    f.write("")
            except OSError as e:
                print(f"warning: failed to clear marker {marker}: {e}")

    # Clean leftover dirs
    for d in ["monitors", "logs"]:
        target = os.path.join(project_root, d)
        if os.path.exists(target):
            shutil.rmtree(target)


def find_session_dir(project_root, log_dir):
    """Find the session directory created by the orchestrator.

    Reads the .autoagent_log marker in project_root to get the session
    subdirectory name, then joins it with log_dir.
    Returns the absolute path, or None if not found.
    """
    marker = os.path.join(project_root, ".autoagent_log")
    if not os.path.exists(marker):
        return None
    try:
        with open(marker, "r", encoding="utf-8") as f:
            subdir_name = f.read().strip()
    except Exception:
        return None
    if not subdir_name:
        return None
    session_dir = os.path.join(log_dir, subdir_name)
    if os.path.isdir(session_dir):
        return session_dir
    return None


def run_orchestrator(project_root, autoagent_dir, test_rules, log_dir,
                     extra_args=None, verbose=False, timeout=30):
    """Run the orchestrator with TestProvider and return the exit code.

    Args:
        timeout: Maximum seconds to wait before killing the process.
                 Default 30s.  Set via "timeout" in test_schema.json.
    """
    orchestrator_py = os.path.join(autoagent_dir, "orchestrator.py")
    todos_yaml = os.path.join(project_root, "todos.yaml")

    cmd_parts = [
        sys.executable, "-X", "utf8",
        orchestrator_py,
        "--config", todos_yaml,
        "--provider", "test",
        "--test-rules", os.path.abspath(test_rules),
        "--workspace", project_root,
        "--preset", "none",
        "--log-dir", log_dir,
        "--verbose",
    ]

    if extra_args:
        cmd_parts.extend(extra_args)

    # Set PYTHONPATH so orchestrator can import its modules
    env = os.environ.copy()
    existing_pypath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = autoagent_dir + (
        os.pathsep + existing_pypath if existing_pypath else ""
    )

    kwargs = {
        "cwd": project_root,
        "env": env,
    }
    if not verbose:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
        kwargs["text"] = True
        kwargs["encoding"] = "utf-8"
        kwargs["errors"] = "replace"

    try:
        result = subprocess.run(cmd_parts, timeout=timeout, **kwargs)
        return result.returncode, result
    except subprocess.TimeoutExpired:
        return -1, None
    except KeyboardInterrupt:
        return 130, None


def _normalize_log_content(text):
    """Normalize session-specific paths in conversation log content.

    Replaces absolute paths to autoagent-exec.bat with a stable placeholder
    and normalizes variable runtime values (PIDs, log file paths) so that
    logs from different runs can be compared.
    """
    text = text.replace("\\", "/")
    # Replace quoted autoagent-exec paths:
    #   "F:/Workspace/.../scripts/autoagent-exec.bat" → "<autoagent-exec>"
    text = re.sub(
        r'"[^"]*?/scripts/autoagent-exec\.(?:bat|sh)"',
        '"<autoagent-exec>"',
        text,
    )
    # Normalize PIDs:  "   PID: 12345" → "   PID: <PID>"
    text = re.sub(r'PID: \d+', 'PID: <PID>', text)
    # Normalize log file paths that contain session IDs:
    #   .../logs/<session_id>/... → .../logs/<SESSION>/...
    text = re.sub(
        r'(?:(?:[A-Za-z]:)?[^"\n]*?/)?logs/(?:<SESSION>|[A-Za-z0-9_.-]+_[a-z0-9]+)/',
        'logs/<SESSION>/',
        text,
    )
    return text


def _normalize_state_data(data):
    """Recursively strip runtime-variable fields from parsed todos_state data."""
    STRIP_KEYS = {'time', 'last_attempt', 'context_created_at'}
    if isinstance(data, dict):
        return {k: _normalize_state_data(v) for k, v in data.items()
                if k not in STRIP_KEYS}
    if isinstance(data, list):
        return [_normalize_state_data(item) for item in data]
    return data


def compare_state_file(session_dir, project_root):
    """Compare actual todos_state.yaml against expected reference.

    Parses both files, strips timestamps, then compares the normalized
    YAML output.  Returns a list of error strings (empty if match).
    """
    import yaml

    expected_path = os.path.join(project_root, "expected_state.yaml")
    if not os.path.isfile(expected_path):
        return []  # No expected state file → skip comparison

    actual_path = os.path.join(session_dir, "todos_state.yaml")
    if not os.path.isfile(actual_path):
        return ["State compare: todos_state.yaml not found in session"]

    with open(expected_path, "r", encoding="utf-8") as f:
        expected_data = yaml.safe_load(f)
    with open(actual_path, "r", encoding="utf-8") as f:
        actual_data = yaml.safe_load(f)

    expected_norm = _normalize_state_data(expected_data)
    actual_norm = _normalize_state_data(actual_data)

    expected_text = yaml.dump(expected_norm, default_flow_style=False,
                              allow_unicode=True, sort_keys=True)
    actual_text = yaml.dump(actual_norm, default_flow_style=False,
                            allow_unicode=True, sort_keys=True)

    if expected_text == actual_text:
        return []

    exp_lines = expected_text.splitlines()
    act_lines = actual_text.splitlines()
    errors = ["State compare: todos_state.yaml content differs"]
    for i, (e, a) in enumerate(zip(exp_lines, act_lines), 1):
        if e != a:
            errors.append(f"  line {i} expected: {e!r}")
            errors.append(f"  line {i} actual:   {a!r}")
            break
    else:
        diff_line = min(len(exp_lines), len(act_lines)) + 1
        if diff_line <= len(exp_lines):
            errors.append(f"  line {diff_line} expected: {exp_lines[diff_line-1]!r}")
        else:
            errors.append("  expected: <EOF>")
        if diff_line <= len(act_lines):
            errors.append(f"  line {diff_line} actual:   {act_lines[diff_line-1]!r}")
        else:
            errors.append("  actual:   <EOF>")
    return errors


def compare_conversation_logs(session_dir, project_root):
    """Compare actual conversation logs against expected reference logs.

    The expected logs live in <project_root>/expected_logs/ and are
    pre-normalized (session-specific paths replaced with placeholders).

    Returns a list of error strings (empty if all match).
    """
    expected_dir = os.path.join(project_root, "expected_logs")
    if not os.path.isdir(expected_dir):
        return [f"Expected logs directory not found: {expected_dir}"]

    actual_conv_dir = os.path.join(session_dir, "conversations")
    if not os.path.isdir(actual_conv_dir):
        return ["Conversations directory not found in session"]

    errors = []

    # Walk the expected_logs directory and compare each file
    for dirpath, _dirnames, filenames in os.walk(expected_dir):
        for fname in sorted(filenames):
            if not fname.endswith(".md"):
                continue
            expected_path = os.path.join(dirpath, fname)
            # Compute relative path from expected_dir
            rel_path = os.path.relpath(expected_path, expected_dir)
            actual_path = os.path.join(actual_conv_dir, rel_path)

            if not os.path.isfile(actual_path):
                errors.append(f"Log compare: missing file {rel_path}")
                continue

            with open(expected_path, "r", encoding="utf-8") as f:
                expected_text = _normalize_log_content(f.read())
            with open(actual_path, "r", encoding="utf-8") as f:
                actual_text = _normalize_log_content(f.read())

            if expected_text != actual_text:
                # Find first difference for diagnostics
                exp_lines = expected_text.splitlines()
                act_lines = actual_text.splitlines()
                diff_line = None
                for i, (e, a) in enumerate(zip(exp_lines, act_lines), 1):
                    if e != a:
                        diff_line = i
                        break
                if diff_line is None:
                    # One is longer than the other
                    diff_line = min(len(exp_lines), len(act_lines)) + 1

                errors.append(
                    f"Log compare: {rel_path} differs at line {diff_line}"
                )
                # Show context around the first diff
                start = max(0, diff_line - 2)
                end = min(max(len(exp_lines), len(act_lines)), diff_line + 2)
                if diff_line <= len(exp_lines):
                    errors.append(f"  expected: {exp_lines[diff_line - 1]!r}")
                else:
                    errors.append(f"  expected: <EOF>")
                if diff_line <= len(act_lines):
                    errors.append(f"  actual:   {act_lines[diff_line - 1]!r}")
                else:
                    errors.append(f"  actual:   <EOF>")

    # Also check for unexpected extra files in actual that aren't in expected
    for dirpath, _dirnames, filenames in os.walk(actual_conv_dir):
        for fname in sorted(filenames):
            if not fname.endswith(".md"):
                continue
            actual_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(actual_path, actual_conv_dir)
            expected_path = os.path.join(expected_dir, rel_path)
            if not os.path.isfile(expected_path):
                # Skip index files (task_N.md) — these are auto-generated summaries
                if re.match(r"task_\d+\.md$", fname):
                    continue
                errors.append(f"Log compare: unexpected file {rel_path}")

    return errors


def verify_test(test_case, session_dir, actual_exit_code):
    """Verify test results against expected outcomes.

    Returns (passed: bool, errors: list[str]).
    """
    import yaml

    errors = []

    # 1. Check for timeout
    if actual_exit_code == -1:
        errors.append("TIMEOUT: orchestrator did not finish within the time limit")
        return False, errors

    # 2. Check exit code
    expected_exit = test_case["expected_exit_code"]
    if actual_exit_code != expected_exit:
        errors.append(
            f"Exit code: expected {expected_exit}, got {actual_exit_code}"
        )

    # 3. Check todos_state.yaml
    if session_dir is None:
        errors.append("Session directory not found (no .autoagent_log marker)")
        return len(errors) == 0, errors

    state_file = os.path.join(session_dir, "todos_state.yaml")
    if not os.path.exists(state_file):
        errors.append(f"todos_state.yaml not found in {session_dir}")
        return len(errors) == 0, errors

    with open(state_file, "r", encoding="utf-8") as f:
        state = yaml.safe_load(f)

    if not state or "tasks" not in state:
        errors.append("todos_state.yaml is empty or malformed")
        return len(errors) == 0, errors

    tasks = state["tasks"]

    def _find_task_state(task_key):
        """Find a task's state, checking plain key first, then @-suffixed keys."""
        if task_key in tasks:
            return tasks[task_key]
        # Search for round-scoped keys (e.g., "1.1@2.1")
        prefix = task_key + "@"
        round_keys = sorted(
            [k for k in tasks if k.startswith(prefix)],
            key=lambda k: k,  # lexicographic sort puts latest round last
        )
        if round_keys:
            return tasks[round_keys[-1]]
        return None

    for task_id, expected in test_case["expected_tasks"].items():
        task_key = str(task_id)
        task_state = _find_task_state(task_key)
        if task_state is None:
            errors.append(f"Task '{task_id}': not found in todos_state.yaml")
            continue

        # Check status
        if "status" in expected:
            actual_status = task_state.get("status", "<missing>")
            if actual_status != expected["status"]:
                errors.append(
                    f"Task '{task_id}': expected status='{expected['status']}', "
                    f"got '{actual_status}'"
                )

        # Check max_history_len (for once-type: history should be short)
        if "max_history_len" in expected:
            history = task_state.get("history", [])
            if len(history) > expected["max_history_len"]:
                errors.append(
                    f"Task '{task_id}': expected history_len <= "
                    f"{expected['max_history_len']}, got {len(history)}"
                )

        # Check has_not_completed (history should contain a not_completed entry)
        # Check across ALL round keys for this task (history may be spread)
        if expected.get("has_not_completed"):
            all_history = list(task_state.get("history", []))
            prefix = str(task_id) + "@"
            for k, v in tasks.items():
                if k.startswith(prefix):
                    all_history.extend(v.get("history", []))
            has_nc = any(
                h.get("result") == "not_completed" for h in all_history
            )
            if not has_nc:
                errors.append(
                    f"Task '{task_id}': expected history to contain a "
                    f"not_completed entry, but none found"
                )

    # 4. Compare conversation logs (only for tests with compare_logs=true)
    if test_case.get("compare_logs") and session_dir:
        project_root = test_case.get("_project_root", "")
        log_errors = compare_conversation_logs(session_dir, project_root)
        errors.extend(log_errors)

    # 5. Compare state file (only for tests with compare_state=true)
    if test_case.get("compare_state") and session_dir:
        project_root = test_case.get("_project_root", "")
        state_errors = compare_state_file(session_dir, project_root)
        errors.extend(state_errors)

    return len(errors) == 0, errors


def cleanup_test(test_case, project_root):
    """Post-test cleanup: restore specific files via git checkout."""
    cleanup_files = test_case.get("cleanup_files", [])
    if cleanup_files:
        for f in cleanup_files:
            subprocess.run(
                f'git checkout -- "{f}"',
                shell=True, cwd=project_root, capture_output=True,
            )


def print_test_list(test_cases):
    """Print the list of available tests."""
    print(f"\n{'=' * 60}")
    print(f"  Available Simulation Tests")
    print(f"{'=' * 60}")
    for i, tc in enumerate(test_cases, 1):
        exit_info = f"exit={tc['expected_exit_code']}"
        print(f"  {i:2d}. {tc['name']}")
        print(f"      project: {tc['project_root']}, rules: {tc['test_rules']}, {exit_info}")
    print(f"{'=' * 60}")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="AutoAgent Simulation Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_test.py                        # Run all tests
  python run_test.py --test 5               # Run only test 5
  python run_test.py --test 5 --test 8      # Run tests 5 and 8
  python run_test.py --verbose              # Show orchestrator output
  python run_test.py --list                 # List available tests
  python run_test.py --test-root /path/to   # Override test root directory
        """,
    )
    parser.add_argument(
        "--test", "-t",
        type=int,
        action="append",
        dest="tests",
        help="Test number(s) to run (1-N). Can be specified multiple times. "
             "Default: run all tests.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show orchestrator stdout/stderr (not captured).",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available tests and exit.",
    )
    parser.add_argument(
        "--test-root",
        default=None,
        help="Path to the test root directory containing test_schema.json "
             "and test project subdirectories. "
             "Default: <script_dir>/test/simulation_test/",
    )

    args = parser.parse_args()

    # Resolve test root: --test-root > default (based on script location)
    if args.test_root:
        test_root = os.path.abspath(args.test_root)
    else:
        test_root = get_default_test_root()

    if not os.path.isdir(test_root):
        print(f"ERROR: Test root directory not found: {test_root}")
        sys.exit(1)

    # Load test definitions from test_schema.json
    test_cases = load_test_schema(test_root)

    if args.list:
        print_test_list(test_cases)
        return

    # Resolve paths
    autoagent_dir = get_script_dir()  # run_test.py lives in autoagent/
    log_dir = os.path.abspath(os.path.join(test_root, "logs"))

    # Validate that we can import yaml
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("ERROR: pyyaml is required. Install with: pip install pyyaml")
        sys.exit(1)

    # Select tests
    if args.tests:
        selected = []
        for t in args.tests:
            if t < 1 or t > len(test_cases):
                print(f"ERROR: Test {t} does not exist (valid: 1-{len(test_cases)})")
                sys.exit(1)
            selected.append((t, test_cases[t - 1]))
    else:
        selected = [(i + 1, tc) for i, tc in enumerate(test_cases)]

    total = len(selected)

    print(f"\n{'=' * 60}")
    print(f"  AutoAgent Simulation Test Runner")
    print(f"  Test root: {test_root}")
    print(f"  Running {total} test(s)")
    print(f"{'=' * 60}")

    results = []  # list of (test_num, name, passed, errors, elapsed)

    for idx, (test_num, tc) in enumerate(selected, 1):
        name = tc["name"]
        project_root = os.path.abspath(
            os.path.join(test_root, tc["project_root"])
        )
        # Store resolved path for verify_test's log comparison
        tc["_project_root"] = project_root
        test_rules = os.path.join(test_root, tc["test_rules"])

        print(f"\n[{idx}/{total}] Test {test_num}: {name}")

        # Validate paths
        if not os.path.isdir(project_root):
            print(f"  SKIP - project directory not found: {project_root}")
            results.append((test_num, name, False, ["Project directory not found"], 0))
            continue
        if not os.path.isfile(test_rules):
            print(f"  SKIP - test rules not found: {test_rules}")
            results.append((test_num, name, False, ["Test rules file not found"], 0))
            continue

        # Ensure git initialized
        ensure_git_initialized(project_root)

        # Reset
        print(f"  Resetting...", end=" ", flush=True)
        reset_test(project_root, log_dir)
        print(f"done")

        # Build extra_args (resolve relative paths)
        extra_args = []
        for arg in tc.get("extra_args", []):
            if arg.startswith("-"):
                extra_args.append(arg)
            elif "." in os.path.basename(arg):
                # Looks like a file path — resolve relative to test_root
                extra_args.append(os.path.abspath(
                    os.path.join(test_root, arg)
                ))
            else:
                extra_args.append(arg)

        # Run
        test_timeout = tc.get("timeout", 30)
        print(f"  Running (timeout={test_timeout}s)...", end=" ", flush=True)
        t0 = time.time()
        exit_code, proc_result = run_orchestrator(
            project_root, autoagent_dir, test_rules, log_dir,
            extra_args=extra_args, verbose=args.verbose,
            timeout=test_timeout,
        )
        elapsed = time.time() - t0

        # Find session dir
        session_dir = find_session_dir(project_root, log_dir)

        # Verify
        passed, errors = verify_test(tc, session_dir, exit_code)

        # Cleanup
        cleanup_test(tc, project_root)

        if passed:
            print(f"PASS ({elapsed:.1f}s)")
        else:
            print(f"FAIL ({elapsed:.1f}s)")
            for err in errors:
                print(f"    - {err}")
            # Show orchestrator output on failure if not verbose mode
            if not args.verbose and proc_result and hasattr(proc_result, "stdout"):
                def _safe_print(s):
                    try:
                        print(s)
                    except UnicodeEncodeError:
                        print(s.encode("utf-8", errors="replace").decode("ascii", errors="replace"))

                if proc_result.stdout:
                    # Show last 30 lines of output
                    lines = proc_result.stdout.strip().split("\n")
                    if len(lines) > 30:
                        print(f"\n  --- Last 30 lines of orchestrator output ---")
                        for line in lines[-30:]:
                            _safe_print(f"    {line}")
                    else:
                        print(f"\n  --- Orchestrator output ---")
                        for line in lines:
                            _safe_print(f"    {line}")
                if proc_result.stderr:
                    stderr_lines = proc_result.stderr.strip().split("\n")
                    print(f"\n  --- Orchestrator stderr (last 15 lines) ---")
                    for line in stderr_lines[-15:]:
                        _safe_print(f"    {line}")

        results.append((test_num, name, passed, errors, elapsed))

    # Summary
    passed_count = sum(1 for _, _, p, _, _ in results if p)
    failed_count = total - passed_count
    total_time = sum(e for _, _, _, _, e in results)

    print(f"\n{'=' * 60}")
    if failed_count == 0:
        print(f"  Results: {passed_count}/{total} PASSED  ({total_time:.1f}s)")
    else:
        print(f"  Results: {passed_count}/{total} PASSED, {failed_count} FAILED  ({total_time:.1f}s)")
        print()
        for test_num, name, passed, errors, _ in results:
            if not passed:
                print(f"  FAILED: Test {test_num} - {name}")
                for err in errors:
                    print(f"    - {err}")
    print(f"{'=' * 60}")

    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
