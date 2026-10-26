#!/usr/bin/env python3
"""Tests for output-guard-hook.py. Run: python3 tests/test_output_guard.py"""
import json, os, subprocess, sys, tempfile
HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "output-guard-hook.py")
big = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False); big.write("x\n" * 500); big.close()
small = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False); small.write("x\n" * 20); small.close()

def run(name, inp):
    out = subprocess.run([sys.executable, HOOK], input=json.dumps({"tool_name": name, "tool_input": inp, "cwd": "/"}),
                         capture_output=True, text=True)
    return bool(out.stdout.strip())

CASES = [
    ("Read big no range -> deny", "Read", {"file_path": big.name}, True),
    ("Read big with limit -> allow", "Read", {"file_path": big.name, "limit": 100}, False),
    ("Read big allow_large -> allow", "Read", {"file_path": big.name, "allow_large": True}, False),
    ("Read small -> allow", "Read", {"file_path": small.name}, False),
    ("cat big -> deny", "Bash", {"command": f"cat {big.name}"}, True),
    ("cat big | head -> allow", "Bash", {"command": f"cat {big.name} | head -20"}, False),
    ("cat small -> allow", "Bash", {"command": f"cat {small.name}"}, False),
    ("cat heredoc write -> allow", "Bash", {"command": "cat > /tmp/x.py <<'EOF'\nprint(1)\nEOF"}, False),
    ("git diff bare -> deny", "Bash", {"command": "git diff"}, True),
    ("git diff --stat -> allow", "Bash", {"command": "git diff --stat"}, False),
    ("git diff path -> allow", "Bash", {"command": "git diff -- api/a.php"}, False),
    ("git -C diff path -> allow", "Bash", {"command": "git -C ~/my-app diff src/a.js"}, False),
    ("git log bare -> deny", "Bash", {"command": "git log"}, True),
    ("git log -n -> allow", "Bash", {"command": "git log --oneline -n 10"}, False),
    ("git log -5 -> allow", "Bash", {"command": "git log -5"}, False),
    ("jest bare -> deny", "Bash", {"command": "npx jest src/x"}, True),
    ("jest tail -> allow", "Bash", {"command": "npx jest src/x 2>&1 | tail -40"}, False),
    ("phpunit grep -> allow", "Bash", {"command": "vendor/bin/phpunit 2>&1 | grep -E 'Tests:|FAIL'"}, False),
    ("tsc bare -> deny", "Bash", {"command": "cd ~/my-app && npx tsc --noEmit"}, True),
    ("find bare -> deny", "Bash", {"command": "find . -name '*.php'"}, True),
    ("find head -> allow", "Bash", {"command": "find . -name '*.php' | head -50"}, False),
    ("#full escape -> allow", "Bash", {"command": "git diff #full"}, False),
    ("commit message naming pytest -> allow", "Bash", {"command": 'git commit -m "Run pytest in the hook."'}, False),
    ("grep for xcodebuild -> allow", "Bash", {"command": "grep -n xcodebuild scripts/x.py"}, False),
    ("echo npm test -> allow", "Bash", {"command": 'echo "see npm test"; ls'}, False),
    ("cd then jest untailed -> deny", "Bash", {"command": "cd a && npx jest foo"}, True),
    ("find maxdepth 1 -> allow", "Bash", {"command": 'find . -maxdepth 1 -name "*.md"'}, False),
    ("find exec -> allow", "Bash", {"command": "find . -name '*.php' -exec php -l {} +"}, False),
    ("git log --since -> allow", "Bash", {"command": "git log --since=1.day"}, False),
    ("git log range -> allow", "Bash", {"command": "git log origin/main..HEAD"}, False),
    ("git diff refs -> allow", "Bash", {"command": "git diff HEAD~1 HEAD"}, False),
    ("git diff --cached -> deny", "Bash", {"command": "git diff --cached"}, True),
    ("heredoc with jest inside -> allow", "Bash", {"command": "cat > /tmp/x.sh <<'EOF'\nnpx jest\nEOF\necho ok"}, False),
    ("ordinary cmd -> allow", "Bash", {"command": "php -l api/a.php && echo ok"}, False),
]
failed = 0
for name, tool, inp, want in CASES:
    got = run(tool, inp); ok = got == want; failed += not ok
    print("PASS" if ok else "FAIL", name)
os.unlink(big.name); os.unlink(small.name)
print("failed:", failed); sys.exit(1 if failed else 0)
