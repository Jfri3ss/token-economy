#!/usr/bin/env python3
"""Tests for output-guard-hook.py. Run: python3 tests/test_output_guard.py"""
import json, os, subprocess, sys, tempfile
HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "output-guard-hook.py")
big = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False); big.write("x\n" * 500); big.close()
small = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False); small.write("x\n" * 20); small.close()

def run(name, inp):
    out = subprocess.run([sys.executable, HOOK], input=json.dumps({"tool_name": name, "tool_input": inp, "cwd": "/"}),
                         capture_output=True, text=True)
    if not out.stdout.strip():
        return False
    hso = json.loads(out.stdout)["hookSpecificOutput"]
    if hso.get("permissionDecision") == "allow":
        return "rewrite:" + hso["updatedInput"]["command"]
    return True

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
    ("git log bare -> rewrite", "Bash", {"command": "git log"}, "rewrite:git log -n 20"),
    ("git log path -> rewrite", "Bash", {"command": "git log --format=%h -- api/a.php"}, "rewrite:git log -n 20 --format=%h -- api/a.php"),
    ("git -C abs log -> deny", "Bash", {"command": "git -C /srv/app log"}, True),
    ("git log chained -> deny", "Bash", {"command": "cd a && git log"}, True),
    ("git log -n -> allow", "Bash", {"command": "git log --oneline -n 10"}, False),
    ("git log -5 -> allow", "Bash", {"command": "git log -5"}, False),
    ("jest bare -> deny", "Bash", {"command": "npx jest src/x"}, True),
    ("jest tail -> allow", "Bash", {"command": "npx jest src/x 2>&1 | tail -40"}, False),
    ("phpunit grep -> allow", "Bash", {"command": "vendor/bin/phpunit 2>&1 | grep -E 'Tests:|FAIL'"}, False),
    ("tsc bare -> deny", "Bash", {"command": "cd ~/my-app && npx tsc --noEmit"}, True),
    ("find bare -> rewrite", "Bash", {"command": "find . -name '*.php'"}, "rewrite:find . -name '*.php' | head -50"),
    ("ls -R -> rewrite", "Bash", {"command": "ls -R src"}, "rewrite:ls -R src | head -50"),
    ("find absolute -> deny", "Bash", {"command": "find /etc -name '*.conf'"}, True),
    ("find home -> deny", "Bash", {"command": "find ~ -name '*.md'"}, True),
    ("find parent -> deny", "Bash", {"command": "find ../other -name x"}, True),
    ("find substitution -> deny", "Bash", {"command": "find $(pwd) -name x"}, True),
    ("find -exec -> no rewrite", "Bash", {"command": "find . -name x -fprint out"}, True),
    ("find brace to root -> deny", "Bash", {"command": "find {/,.} -name x"}, True),
    ("ls brace to parent -> deny", "Bash", {"command": "ls -R .{.,}"}, True),
    ("find empty quotes root -> deny", "Bash", {"command": 'find ""/etc -name x'}, True),
    ("find escaped root -> deny", "Bash", {"command": "find \\/etc -name x"}, True),
    ("tree -o -> deny", "Bash", {"command": "tree -o out.txt"}, True),
    ("git log --output -> deny", "Bash", {"command": "git log --output=x.txt"}, True),
    ("git log --ext-diff -> deny", "Bash", {"command": "git log -p --ext-diff"}, True),
    ("find -okdir -> deny", "Bash", {"command": "find . -okdir rm {} +"}, True),
    ("find comment -> deny", "Bash", {"command": "find . #x"}, True),
    ("find -L -> deny", "Bash", {"command": "find -L . -name x"}, True),
    ("ls -RL -> deny", "Bash", {"command": "ls -RL src"}, True),
    ("ls -R unquoted glob -> deny", "Bash", {"command": "ls -R .*"}, True),
    ("git -C path with log in it -> rewrite at subcommand", "Bash", {"command": "git -C logs/log log"}, "rewrite:git -C logs/log log -n 20"),
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
# Each denial names its rule so the ledger can count overrides per rule.
for tool, inp, rule in (("Read", {"file_path": big.name}, "read-large"), ("Bash", {"command": "git diff"}, "git-diff"),
                        ("Bash", {"command": "find /srv"}, "listing")):
    out = subprocess.run([sys.executable, HOOK], input=json.dumps({"tool_name": tool, "tool_input": inp, "cwd": "/"}),
                         capture_output=True, text=True).stdout
    ok = f"[guard rule: {rule}]" in out; failed += not ok
    print("PASS" if ok else "FAIL", f"denial tagged {rule}")
# Each rewrite is tagged too, and keeps the other input fields.
out = json.loads(subprocess.run([sys.executable, HOOK], input=json.dumps(
    {"tool_name": "Bash", "tool_input": {"command": "find .", "description": "list", "timeout": 5000}, "cwd": "/"}),
    capture_output=True, text=True).stdout)["hookSpecificOutput"]
ok = ("[guard rewrite: listing]" in out["additionalContext"] and out["updatedInput"]["description"] == "list"
      and out["updatedInput"]["timeout"] == 5000); failed += not ok
print("PASS" if ok else "FAIL", "rewrite tagged and keeps other fields")
os.unlink(big.name); os.unlink(small.name)
print("failed:", failed); sys.exit(1 if failed else 0)
