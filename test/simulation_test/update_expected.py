import os
import re

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
    #   D:/silasshen/.../logs/<SESSION>/ → logs/<SESSION>/
    text = re.sub(
        r'[A-Za-z]:[^"\s]*/logs/<SESSION>/',
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

base_dir = os.path.dirname(os.path.abspath(__file__))
update_expected_logs(os.path.join(base_dir, "logs"), "comprehensive_test", os.path.join(base_dir, "comprehensive_test", "expected_logs"))
update_expected_logs(os.path.join(base_dir, "logs"), "comprehensive_ai_sched_test", os.path.join(base_dir, "comprehensive_ai_sched_test", "expected_logs"))