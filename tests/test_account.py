#!/usr/bin/env python3
"""End-to-end tests for scripts/account.py, the sync hook and the ledger, against server/dev.mjs.

Run: python3 tests/test_account.py   (needs Node 22.5+ for node:sqlite; skips the server part without it)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ACCOUNT = os.path.join(ROOT, "scripts", "account.py")
LEDGER = os.path.join(ROOT, "scripts", "token-ledger.py")
SYNC_HOOK = os.path.join(ROOT, "hooks", "account-sync-hook.py")
passed = failed = 0


def check(name, ok):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print("FAIL", name)


home = tempfile.mkdtemp()
proj = os.path.join(home, ".claude", "projects", "-Users-dev-app")
os.makedirs(proj)
day = time.strftime("%Y-%m-%d", time.gmtime())


def entry(kind, content, usage=None):
    m = {"content": content}
    if usage:
        m["usage"] = usage
        m["model"] = "claude-opus-5-5"
    return json.dumps({"type": kind, "timestamp": f"{day}T10:00:00Z", "message": m})


lines = [
    entry("user", "Secret prompt about Project Falcon"),
    entry("assistant", [{"type": "tool_use", "id": "1", "name": "Bash", "input": {"command": "git diff"}}], {"input_tokens": 1000, "output_tokens": 50}),
    entry("user", [{"type": "tool_result", "tool_use_id": "1", "is_error": True,
                    "content": "PreToolUse:Bash hook error: git diff with no path can be thousands of lines. Run it with --stat first, then diff the paths you need (git diff -- path), or add #full."}]),
    entry("assistant", [{"type": "tool_use", "id": "2", "name": "Bash", "input": {"command": "git diff #full"}}], {"input_tokens": 1200, "output_tokens": 40}),
    entry("user", [{"type": "tool_result", "tool_use_id": "2", "content": "diff --git a/secret.py"}]),
    entry("assistant", [{"type": "tool_use", "id": "3", "name": "Bash", "input": {"command": "find ."}}], {"input_tokens": 1300, "output_tokens": 10}),
    entry("user", [{"type": "tool_result", "tool_use_id": "3", "is_error": True,
                    "content": "PreToolUse:Bash hook error: That listing can be very long. Pipe it through | head -50 or narrow it, or add #full."}]),
    entry("assistant", [{"type": "tool_use", "id": "4", "name": "Bash", "input": {"command": "find . | head -50"}}], {"input_tokens": 1400, "output_tokens": 10}),
    entry("user", [{"type": "tool_result", "tool_use_id": "4", "content": "./a"}]),
    entry("assistant", [{"type": "text", "text": "I mentioned #full in prose."}], {"input_tokens": 1500, "output_tokens": 10}),
    entry("assistant", [{"type": "tool_use", "id": "5", "name": "Bash", "input": {"command": "git log"}}], {"input_tokens": 1500, "output_tokens": 10}),
    entry("user", [{"type": "tool_result", "tool_use_id": "5", "is_error": True,
                    "content": "PreToolUse:Bash hook error: git log without a count prints the whole history. Add -n 20 (and --oneline)."}]),
    entry("assistant", [{"type": "text", "text": "Thinking."}], {"input_tokens": 1500, "output_tokens": 10}),
    entry("assistant", [{"type": "tool_use", "id": "6", "name": "Bash", "input": {"command": "git log #full"}}], {"input_tokens": 1500, "output_tokens": 10}),
    entry("user", [{"type": "tool_result", "tool_use_id": "6", "content": "commit abc"}]),
]
# One step written as two lines (text, then the tool call) with the same id and usage, as Claude Code does.
def split(mid, blocks, usage):
    return [json.dumps({"type": "assistant", "timestamp": f"{day}T11:00:00Z",
                        "message": {"id": mid, "content": [b], "usage": usage, "model": "claude-opus-5-5"}}) for b in blocks]
u7 = {"input_tokens": 2000, "output_tokens": 30}
lines += split("m7", [{"type": "tool_use", "id": "7", "name": "Read", "input": {"file_path": "/x"}}], u7)
lines.append(entry("user", [{"type": "tool_result", "tool_use_id": "7", "is_error": True,
                             "content": "PreToolUse:Read hook error: x.py has 900 lines. Read the part you need with offset and limit, or grep for the symbol first; pass allow_large only if you truly need all of it."}]))
lines += split("m8", [{"type": "text", "text": "Need all of it."},
                      {"type": "tool_use", "id": "8", "name": "Read", "input": {"file_path": "/x", "allow_large": True}}], u7)
with open(os.path.join(proj, "s1.jsonl"), "w") as f:
    f.write("\n".join(lines) + "\n")

env = dict(os.environ, HOME=home, TOKEN_ECONOMY_CONFIG="/nonexistent/none.json")
env["TOKEN_ECONOMY_ENDPOINT"] = "off"  # never reach the live server from tests

# Ledger: denials need the hook's error shape; an override is the same tool rerun with #full straight after.
out = subprocess.run([sys.executable, LEDGER, "--project", "/Users/dev/app"], env=env, capture_output=True, text=True).stdout
row = next((l for l in out.splitlines() if l.startswith("s1")), "")
check("ledger counts 4 denials and 2 overrides (only the very next step)", re.search(r"\s4\s+2\s+Secret", row) is not None)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("ledger", LEDGER)
ledger = importlib.util.module_from_spec(spec)
os.environ["HOME"] = home
spec.loader.exec_module(ledger)
r = ledger.rollup(30)
c = r[day]["-Users-dev-app"]
check("rollup counts split steps once", c["steps"] == 10 and c["reread"] == 14900 and c["denials"] == 4 and c["overrides"] == 2 and c["sessions"] == 1)

# No endpoint: accounts are off and say so.
p = subprocess.run([sys.executable, ACCOUNT, "login"], env=env, capture_output=True, text=True)
check("login without endpoint explains", p.returncode != 0 and "aren't open yet" in p.stderr)
p = subprocess.run([sys.executable, ACCOUNT, "status"], env=env, capture_output=True, text=True)
check("status signed out", "Not signed in" in p.stdout)
# A project's config file must not redirect the key; plain http only to localhost.
cfg_dir = tempfile.mkdtemp()
with open(os.path.join(cfg_dir, "token-economy.config.json"), "w") as f:
    json.dump({"account_endpoint": "https://evil.example"}, f)
probe = [sys.executable, "-c", f"import importlib.util as u; s = u.spec_from_file_location('a', {ACCOUNT!r}); "
         "m = u.module_from_spec(s); s.loader.exec_module(m); print(m.endpoint() == m.DEFAULT_ENDPOINT, m.endpoint())"]
noenv = {k: v for k, v in env.items() if k != "TOKEN_ECONOMY_ENDPOINT"}
p = subprocess.run(probe, env=noenv, cwd=cfg_dir, capture_output=True, text=True)
check("project config can't set the endpoint", p.stdout.startswith("True") and "evil" not in p.stdout)
with open(os.path.join(home, ".claude", "token-economy.config.json"), "w") as f:
    json.dump({"account_endpoint": "http://evil.example"}, f)
p = subprocess.run(probe, env=noenv, capture_output=True, text=True)
check("plain http to a remote host refused", p.stdout.strip() == "False")
os.remove(os.path.join(home, ".claude", "token-economy.config.json"))
check("sync hook quiet when signed out", subprocess.run([sys.executable, SYNC_HOOK], input="{}", env=env, capture_output=True, text=True).stdout == "")

if not shutil.which("node"):
    print("skip: node not found")
else:
    srv = subprocess.Popen(["node", os.path.join(ROOT, "server", "dev.mjs")], stdout=subprocess.PIPE, text=True)
    try:
        port = srv.stdout.readline().split()[-1]
        base = f"http://127.0.0.1:{port}"
        env["TOKEN_ECONOMY_ENDPOINT"] = base
        login = subprocess.Popen([sys.executable, ACCOUNT, "login", "--upload"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        first = login.stdout.readline()
        code = re.search(r"code ([A-Z]{4}-[A-Z]{4})", first).group(1)
        form = urllib.parse.urlencode({"user_code": code, "email": "dev@example.com"}).encode()
        page = urllib.request.urlopen(urllib.request.Request(base + "/activate", data=form)).read().decode()
        link = re.search(r'href="([^"]+/confirm\?t=[a-f0-9]+)"', page).group(1)
        shown = urllib.request.urlopen(link).read().decode()
        check("confirm page shows the code", code in shown)
        urllib.request.urlopen(urllib.request.Request(base + "/confirm", data=urllib.parse.urlencode({"t": link.split("?t=")[1]}).encode())).read()
        rest, err = login.communicate(timeout=30)
        check("login completes", login.returncode == 0 and "Signed in as dev@example.com" in rest)
        check("login --upload syncs", "Uploaded 1 day-project rows" in rest)
        state_path = os.path.join(home, ".claude", "token-economy", "account.json")
        state = json.load(open(state_path))
        check("key saved with 0600", oct(os.stat(state_path).st_mode & 0o777) == "0o600" and state["api_key"].startswith("te_"))
        req = urllib.request.Request(base + "/v1/usage?days=30", headers={"Authorization": "Bearer " + state["api_key"]})
        days = json.loads(urllib.request.urlopen(req).read())["days"]
        check("server has the counts", len(days) == 1 and days[0]["steps"] == 10 and days[0]["overrides"] == 2)
        p = subprocess.run([sys.executable, ACCOUNT, "status"], env=env, capture_output=True, text=True)
        check("status shows plan", "Plan: free" in p.stdout and "dashboard" in p.stdout)
        # What leaves the machine: counts and hashes only.
        spec2 = importlib.util.spec_from_file_location("account", ACCOUNT)
        account = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(account)
        sent = json.dumps(account.payload(state, 30))
        check("payload has no prompt, path or output text", not any(s in sent for s in ("Falcon", "dev-app", "secret.py", "Users")))
        # The hook spawns a sync only when one is due.
        state["last_sync"] = 0
        state["last_sync_attempt"] = 0
        json.dump(state, open(state_path, "w"))
        h = subprocess.run([sys.executable, SYNC_HOOK], input='{"hook_event_name":"PreToolUse"}', env=env, capture_output=True, text=True)
        time.sleep(1)
        check("sync hook ignores other events", not json.load(open(state_path)).get("last_sync"))
        h = subprocess.run([sys.executable, SYNC_HOOK], input='{"hook_event_name":"SessionStart"}', env=env, capture_output=True, text=True, timeout=5)
        check("sync hook prints nothing", h.stdout == "" and h.returncode == 0)
        for _ in range(50):
            if json.load(open(state_path)).get("last_sync"):
                break
            time.sleep(0.1)
        check("sync hook ran a background sync", bool(json.load(open(state_path)).get("last_sync")))
        p = subprocess.run([sys.executable, ACCOUNT, "upload", "off"], env=env, capture_output=True, text=True)
        check("upload off", "is off" in p.stdout and json.load(open(state_path))["upload"] is False)
        p = subprocess.run([sys.executable, ACCOUNT, "logout", "--delete"], env=env, capture_output=True, text=True)
        check("logout --delete", "deleted" in p.stdout and "api_key" not in json.load(open(state_path)))
        try:
            urllib.request.urlopen(req)
            check("key dead after delete", False)
        except urllib.error.HTTPError as e:
            check("key dead after delete", e.code == 401)
    finally:
        srv.terminate()

shutil.rmtree(home, ignore_errors=True)
print(f"passed: {passed}, failed: {failed}")
