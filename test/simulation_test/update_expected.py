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
    text = re.sub(
        r'(?:(?:[A-Za-z]:)?[^"\n]*?/)?logs/(?:<SESSION>|[A-Za-z0-9_.-]+_[a-z0-9]+)/',
        'logs/<SESSION>/',
        text,
    )
    return text

base_dir = os.path.dirname(os.path.abspath(__file__))

src_base = os.path.join(base_dir, "logs")
dst_base = os.path.join(base_dir, "comprehensive_test", "expected_logs")

dirs = [d for d in os.listdir(src_base) if d.startswith("comprehensive_test")]
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
            
print("Updated expected logs.")