import os
import re


STRIP_KEYS = {'time', 'last_attempt', 'context_created_at', 'timestamp'}

# Regex: a YAML line whose key (after optional indent) is one of STRIP_KEYS.
# Matches  "    time: '2026-04-07 17:29:24'"  or  "  context_created_at: ..."
_STRIP_LINE_RE = re.compile(
    r'^(\s*)(' + '|'.join(re.escape(k) for k in STRIP_KEYS) + r'):.*$'
)

# Regex: fatal_analysis key with runtime timestamp suffix
#   "  fatal_analysis:8.2:1779001957:"  →  "  fatal_analysis:8.2:"
_FATAL_KEY_RE = re.compile(
    r'^(\s*)(fatal_analysis:\d+\.\d+):\d+(:?)$'
)


def _normalize_state_text(text: str) -> str:
    """Strip runtime-variable lines and normalize fatal_analysis keys."""
    lines = text.splitlines(True)
    out = []
    for line in lines:
        if _STRIP_LINE_RE.match(line):
            continue
        m = _FATAL_KEY_RE.match(line.rstrip('\n'))
        if m:
            line = m.group(1) + m.group(2) + m.group(3) + '\n'
        out.append(line)
    return ''.join(out)


def _normalize_log_content(text):
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
    return text

def update_expected_logs(src_base, dir_name, dst_base):
    dirs = [d for d in os.listdir(src_base) if d.startswith(dir_name)]
    latest = max(dirs, key=lambda d: os.path.getmtime(os.path.join(src_base, d)))
    src_conv = os.path.join(src_base, latest, "conversations")

    for root, _, files in os.walk(src_conv):
        for file in files:
            if not file.endswith(".md"): continue
            if re.match(r"task_\d+\.md$", file): continue
            
            src_path = os.path.join(root, file)
            rel_path = os.path.relpath(src_path, src_conv)
            dst_path = os.path.join(dst_base, rel_path)
            
            with open(src_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            norm_content = _normalize_log_content(content)
            
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            with open(dst_path, "w", encoding="utf-8") as f:
                f.write(norm_content)
            print(f"Copied {src_path} to {dst_path}")
                
    print(f"Updated expected logs from {src_base} to {dst_base}")

def update_expected_state(src_base, dir_name, dst_dir):
    """Copy and normalize todos_state.yaml → expected_state.yaml."""
    dirs = [d for d in os.listdir(src_base) if d.startswith(dir_name)]
    latest = max(dirs, key=lambda d: os.path.getmtime(os.path.join(src_base, d)))
    src_state = os.path.join(src_base, latest, "todos_state.yaml")
    dst_state = os.path.join(dst_dir, "expected_state.yaml")

    with open(src_state, "r", encoding="utf-8") as f:
        text = f.read()

    norm = _normalize_state_text(text)

    with open(dst_state, "w", encoding="utf-8") as f:
        f.write(norm)

    print(f"Updated {dst_state}")

base_dir = os.path.dirname(os.path.abspath(__file__))
logs_dir = os.path.join(base_dir, "logs")

for name in ["comprehensive_test", "comprehensive_ai_sched_test"]:
    project_dir = os.path.join(base_dir, name)
    update_expected_logs(logs_dir, name, os.path.join(project_dir, "expected_logs"))
    update_expected_state(logs_dir, name, project_dir)