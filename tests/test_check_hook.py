#!/usr/bin/env python3
"""Tier tests for check-your-work-hook.py. Run: python3 tests/test_check_hook.py"""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "check-your-work-hook.py")


def entry(kind, content):
    return json.dumps({"type": kind, "message": {"content": content}})


def tool(name, inp):
    return entry("assistant", [{"type": "tool_use", "id": "x", "name": name, "input": inp}])


def text(s):
    return entry("assistant", [{"type": "text", "text": s}])


def user(s):
    return entry("user", s)


def run(lines, event="Stop"):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(lines) + "\n")
    data = {"hook_event_name": event, "transcript_path": f.name, "stop_hook_active": False}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=os.path.dirname(os.path.dirname(HOOK)), TOKEN_ECONOMY_CONFIG="/nonexistent/none.json")
    out = subprocess.run([sys.executable, HOOK], input=json.dumps(data), capture_output=True, text=True, env=env)
    os.unlink(f.name)
    return json.loads(out.stdout) if out.stdout.strip() else None


CASES = [
    ("no change -> no block", [user("hi"), text("done")], None),
    ("md edit only -> no block", [user("fix doc"), tool("Edit", {"file_path": "/x/OPEN-TODOS.md"})], None),
    ("memory write -> no block", [user("x"), tool("Write", {"file_path": "/Users/me/.claude/projects/p/memory/a.md"})], None),
    ("php edit -> local", [user("fix"), tool("Edit", {"file_path": "/x/api/a.php"})], "local"),
    ("php edit then commit -> shipped", [user("fix"), tool("Edit", {"file_path": "/x/api/a.php"}),
                                         tool("Bash", {"command": "git commit -m 'x.'"})], "shipped"),
    ("deploy -> deploy", [user("ship"), tool("Bash", {"command": "DEPLOY_HOST=prod ./deploy.sh --pull-only"})], "deploy"),
    ("ssh -> deploy", [user("x"), tool("Bash", {"command": "ssh prod 'crontab -l'"})], "deploy"),
    ("report in reply -> no block", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
                                     text("**Check: clean**\n- Changed: a.php")], None),
    ("skill ran -> no block", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
                               tool("Skill", {"skill": "check-your-work"})], None),
    ("change after report -> local", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
                                      text("**Check: clean**"), tool("Edit", {"file_path": "/x/b.js"})], "local"),
    ("owner says skip -> no block", [user("do it, skip the check"), tool("Edit", {"file_path": "/x/a.php"})], None),
    ("heredoc mentioning deploy -> local", [user("x"), tool("Bash", {"command": "cat > /x/hook.py <<'EOF'\nDEPLOY = 'deploy.sh'\nssh host\nEOF\npython3 -m py_compile /x/hook.py"})], "local"),
    ("heredoc then real deploy -> deploy", [user("x"), tool("Bash", {"command": "cat > /x/a.md <<'EOF'\nnotes\nEOF\n./deploy.sh --pull-only"})], "deploy"),
    ("scratch-only bash -> no block", [user("x"), tool("Bash", {"command": "echo hi > /private/tmp/claude-501/s/out.txt"})], None),
]

failed = 0
for name, lines, want in CASES:
    out = run(lines)
    got = None
    if out:
        reason = out.get("reason", "")
        got = reason.split("tier: ")[1].split(")")[0] if "tier: " in reason else "?"
        if "do not run again" not in reason:
            got += " (no facts)"
    ok = got == want
    failed += not ok
    print(("PASS" if ok else "FAIL"), name, "->", got)
print("failed:", failed)
sys.exit(1 if failed else 0)
