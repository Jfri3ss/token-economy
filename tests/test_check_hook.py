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
    ("check subagent launched -> no block", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
        tool("Agent", {"subagent_type": "general-purpose", "prompt": "read /p/skills/check-your-work/SKILL.md and run sections 1, 3 and 4"})], None),
    ("other subagent -> still local", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
        tool("Agent", {"prompt": "review the diff for bugs"})], "local"),
    ("change after check subagent -> local", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
        tool("Agent", {"prompt": "read /p/skills/check-your-work/SKILL.md"}), tool("Edit", {"file_path": "/x/b.js"})], "local"),
    ("report in agent result -> no block", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
        entry("assistant", [{"type": "tool_use", "id": "ag1", "name": "Agent", "input": {"prompt": "review"}}]),
        user([{"type": "tool_result", "tool_use_id": "ag1", "content": [{"type": "text", "text": "**Check: found problems**\n- Changed: a.php"}]}])], None),
    ("report line in a file read -> still local", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
        entry("assistant", [{"type": "tool_use", "id": "rd1", "name": "Bash", "input": {"command": "sed -n 1,40p tests/t.py"}}]),
        user([{"type": "tool_result", "tool_use_id": "rd1", "content": "text('**Check: clean**')"}])], "local"),
    ("report in relayed agent message -> no block", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
        user("<agent-message>\n  **Check: clean**\n  - Changed: a.php\n</agent-message>")], None),
    ("not needed line -> no block", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
        text("**Check: not needed** - the check ran earlier this turn.")], None),
    ("not needed after deploy -> deploy", [user("ship"), tool("Bash", {"command": "./deploy.sh --pull-only"}),
        text("**Check: not needed**")], "deploy"),
    ("change after not needed -> local", [user("fix"), tool("Edit", {"file_path": "/x/a.php"}),
        text("**Check: not needed**"), tool("Edit", {"file_path": "/x/b.js"})], "local"),
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
# Facts cover only the repos the changes touch; a change with no repo path means all of them.
import importlib.util
cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
json.dump({"repos": {"app": "/r/app", "server": "/r/server"}}, cfg); cfg.close()
os.environ["TOKEN_ECONOMY_CONFIG"] = cfg.name
spec = importlib.util.spec_from_file_location("check", HOOK); h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
for name, changes, want in (
        ("one repo", [("local", "Edit /r/app/a.js")], ["app"]),
        ("two repos", [("local", "Edit /r/app/a.js"), ("local", "Bash sed -i x /r/server/b.php")], ["app", "server"]),
        ("prefix is not a repo", [("local", "Edit /r/application/a.js")], []),
        ("commit with no path", [("local", "Edit /r/app/a.js"), ("shipped", "Bash git commit -m 'x.'")], [])):
    got = h.touched_repos(changes); ok = got == want; failed += not ok
    print(("PASS" if ok else "FAIL"), "facts repos:", name, "->", got)
os.unlink(cfg.name)
print("failed:", failed)
sys.exit(1 if failed else 0)
