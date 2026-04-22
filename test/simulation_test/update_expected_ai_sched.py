"""
Update expected files for the AI Scheduler Comprehensive Test (K7).

Copies:
  1. ai_scheduler/*.md logs → ai_sched_comprehensive/expected_logs/ai_scheduler/
  2. todos_state.yaml       → ai_sched_comprehensive/expected_state.yaml

Both are normalized (session-specific paths replaced with placeholders,
timestamps stripped from state) so that logs from different runs can be
compared deterministically.

Usage:
    python update_expected_ai_sched.py
"""

import os
import re
import shutil
import yaml


def _normalize_log_content(text, project_root=None):
    """Normalize session-specific paths in conversation log content."""
    text = text.replace("\\", "/")
    text = re.sub(
        r'"[^"]*?/scripts/autoagent-exec\.(?:bat|sh)"',
        '"<autoagent-exec>"',
        text,
    )
    text = re.sub(r'PID \d+', 'PID <PID>', text)
    # Step 1: Replace session IDs in log paths:
    #   logs/comprehensive_test_ph0rk2pf/ → logs/<SESSION>/
    text = re.sub(
        r'logs/(?:<SESSION>|[A-Za-z0-9_.-]+_[a-z0-9]+)/',
        'logs/<SESSION>/',
        text,
    )
    # Step 2: Strip absolute path prefixes before logs/<SESSION>/:
    #   D:/.../logs/<SESSION>/ → logs/<SESSION>/       (Windows)
    #   /home/user/.../logs/<SESSION>/   → logs/<SESSION>/       (Linux)
    text = re.sub(
        r'(?:[A-Za-z]:|/)[^"\s]*/logs/<SESSION>/',
        'logs/<SESSION>/',
        text,
    )
    # Step 3: Replace project_root absolute path with <PROJECT_ROOT>
    #   (for type=file last_result paths)
    if project_root:
        pr = project_root.replace("\\", "/")
        text = text.replace(pr, "<PROJECT_ROOT>")
    return text


STRIP_KEYS = {'time', 'last_attempt', 'context_created_at', 'timestamp'}

def _normalize_state_data(data):
    """Recursively strip runtime-variable fields from parsed todos_state data."""
    if isinstance(data, dict):
        return {k: _normalize_state_data(v) for k, v in data.items()
                if k not in STRIP_KEYS}
    if isinstance(data, list):
        return [_normalize_state_data(item) for item in data]
    return data


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    src_base = os.path.join(base_dir, "logs")
    dst_base = os.path.join(base_dir, "ai_sched_comprehensive")

    # Find the latest ai_sched_comprehensive session directory
    if not os.path.isdir(src_base):
        print(f"ERROR: logs directory not found: {src_base}")
        return

    dirs = [d for d in os.listdir(src_base) if d.startswith("ai_sched_comprehensive")]
    if not dirs:
        print("ERROR: No ai_sched_comprehensive session found in logs/")
        print("       Run the test first: python run_test.py --test <N>")
        return

    latest = max(dirs, key=lambda d: os.path.getmtime(os.path.join(src_base, d)))
    session_dir = os.path.join(src_base, latest)
    print(f"Source session: {session_dir}")

    # --- 1. Copy ai_scheduler/ logs ---
    src_sched = os.path.join(session_dir, "conversations", "ai_scheduler")
    dst_sched = os.path.join(dst_base, "expected_logs", "ai_scheduler")

    if not os.path.isdir(src_sched):
        print(f"ERROR: ai_scheduler directory not found: {src_sched}")
        return

    # Clean destination
    if os.path.isdir(dst_sched):
        shutil.rmtree(dst_sched)
    os.makedirs(dst_sched, exist_ok=True)

    count = 0
    for fname in sorted(os.listdir(src_sched)):
        if not fname.endswith(".md"):
            continue
        src_path = os.path.join(src_sched, fname)
        dst_path = os.path.join(dst_sched, fname)

        with open(src_path, "r", encoding="utf-8") as f:
            content = f.read()

        norm_content = _normalize_log_content(content, project_root=dst_base)

        with open(dst_path, "w", encoding="utf-8") as f:
            f.write(norm_content)
        print(f"  Copied: ai_scheduler/{fname}")
        count += 1

    print(f"  Total: {count} log file(s)")

    # --- 2. Copy and normalize todos_state.yaml ---
    src_state = os.path.join(session_dir, "todos_state.yaml")
    dst_state = os.path.join(dst_base, "expected_state.yaml")

    if not os.path.isfile(src_state):
        print(f"ERROR: todos_state.yaml not found: {src_state}")
        return

    with open(src_state, "r", encoding="utf-8") as f:
        state_data = yaml.safe_load(f)

    norm_state = _normalize_state_data(state_data)

    with open(dst_state, "w", encoding="utf-8") as f:
        yaml.dump(norm_state, f, default_flow_style=False,
                  allow_unicode=True, sort_keys=True)
    print(f"  Updated: expected_state.yaml")

    print("\nDone! Expected files updated successfully.")


if __name__ == "__main__":
    main()
