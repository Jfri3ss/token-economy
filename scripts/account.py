#!/usr/bin/env python3
"""Optional free token-economy account. Nothing here runs unless you run it.

    python3 scripts/account.py login [--upload]   create or sign in to an account (device code)
    python3 scripts/account.py status             who you are, your plan, whether uploads are on
    python3 scripts/account.py upload on|off      turn the daily summary upload on or off
    python3 scripts/account.py sync [--quiet]     upload the last 30 days of summary numbers now
    python3 scripts/account.py dashboard          open your savings dashboard in the browser
    python3 scripts/account.py logout [--delete]  forget the key here; --delete also erases the account

Uploads are off until you turn them on. What is sent: per day and per project, counts only
(sessions, steps, tokens re-read, output tokens, tool-output bytes, check blocks and runs, guard
denials and overrides). Projects are sent as a salted hash, never a path or name. No prompts,
titles, code, file names or tool output ever leave the machine. See PRIVACY.md.

The plugin's hooks work the same with or without an account.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))

VERSION = "0.2.0"
# Set at release once the account server is live; until then accounts are off unless configured.
DEFAULT_ENDPOINT = ""
STATE = os.path.expanduser("~/.claude/token-economy/account.json")
HOME_CONFIG = os.path.expanduser("~/.claude/token-economy.config.json")


def endpoint():
    """The env var, then the home config only: a project's config file can't redirect your key."""
    url = os.environ.get("TOKEN_ECONOMY_ENDPOINT") or ""
    if not url:
        try:
            with open(HOME_CONFIG, encoding="utf-8") as f:
                url = (json.load(f) or {}).get("account_endpoint") or ""
        except (OSError, ValueError, AttributeError):
            url = ""
    url = (url or DEFAULT_ENDPOINT).rstrip("/")
    u = urllib.parse.urlparse(url)
    if url and not (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"))):
        return ""
    return url


def read_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(data):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = f"{STATE}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STATE)


def merge_state(key, **fields):
    """Re-read the file and set fields only if the same key is still signed in, so a logout or
    `upload off` that happened meanwhile is never undone."""
    state = read_state()
    if state.get("api_key") != key:
        return state
    state.update(fields)
    write_state(state)
    return state


def call(method, path, body=None, key=None, timeout=15):
    req = urllib.request.Request(endpoint() + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", f"token-economy/{VERSION}")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError) as e:
        return 0, {"error": f"can't reach the account server ({e.__class__.__name__})"}


def need_endpoint():
    if not endpoint():
        sys.exit("Accounts aren't open yet. The plugin works fully without one.")


def need_key(state):
    if not state.get("api_key"):
        sys.exit("Not signed in. Run: python3 scripts/account.py login")


def cmd_login(a):
    need_endpoint()
    state = read_state()
    status, start = call("POST", "/v1/device/start", {"client": f"token-economy/{VERSION}"})
    if status != 200 or "device_code" not in start:
        sys.exit(f"Couldn't start sign-in ({status}): {start.get('error', 'no answer')}")
    print(f"Open {start['verify_url']} and enter the code {start['user_code']}.", flush=True)
    print("Waiting for you to confirm in the browser...", flush=True)
    if sys.stdout.isatty():
        try:
            webbrowser.open(start["verify_url"])
        except Exception:
            pass
    deadline = time.time() + int(start.get("expires_in", 600))
    while time.time() < deadline:
        time.sleep(max(0, float(start.get("interval", 3))))
        status, poll = call("POST", "/v1/device/poll", {"device_code": start["device_code"]})
        if status == 200 and poll.get("api_key"):
            state.update({"api_key": poll["api_key"], "email": poll.get("email", ""), "plan": poll.get("plan", "free"),
                          "device_id": state.get("device_id") or uuid.uuid4().hex,
                          "salt": state.get("salt") or uuid.uuid4().hex, "upload": bool(a.upload or state.get("upload"))})
            write_state(state)
            print(f"Signed in as {state['email']} on the {state['plan']} plan.")
            if state["upload"]:
                print("Daily summary upload is on.")
                sync(state, quiet=False)
            else:
                print("Uploads are off. Turn them on with: python3 scripts/account.py upload on")
            return
        if status not in (0, 202):
            sys.exit(f"Sign-in failed ({status}): {poll.get('error', 'no answer')}")
    sys.exit("The code expired. Run login again.")


def cmd_status(a):
    state = read_state()
    if not state.get("api_key"):
        print("Not signed in. The plugin works fully without an account.")
        return
    line = f"Signed in as {state.get('email', '?')}. Uploads {'on' if state.get('upload') else 'off'}"
    if state.get("last_sync"):
        line += f", last sync {time.strftime('%Y-%m-%d %H:%M', time.localtime(state['last_sync']))}"
    print(line + ".")
    if endpoint():
        status, me = call("GET", "/v1/me", key=state["api_key"])
        if status == 200:
            feats = ", ".join(k for k, v in sorted((me.get("entitlements") or {}).items()) if v)
            print(f"Plan: {me.get('plan', '?')}. Includes: {feats or 'nothing extra'}.")
        else:
            print(f"Couldn't reach the account server ({status}).")


def cmd_upload(a):
    state = read_state()
    need_key(state)
    state["upload"] = a.state == "on"
    write_state(state)
    print(f"Daily summary upload is {a.state}.")
    if state["upload"]:
        sync(state, quiet=False)


def payload(state, days):
    import importlib.util
    spec = importlib.util.spec_from_file_location("ledger", os.path.join(HERE, "token-ledger.py"))
    ledger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ledger)
    rows = []
    for day, projects in sorted(ledger.rollup(days).items()):
        for folder, c in projects.items():
            project = hashlib.sha256((state["salt"] + folder).encode()).hexdigest()[:16]
            rows.append({"day": day, "project": project, **{k: int(c[k]) for k in ("sessions",) + ledger.COUNTS}})
    return {"device_id": state["device_id"], "version": VERSION, "rows": rows}


def sync(state, quiet=False, days=30):
    if not (state.get("api_key") and state.get("upload") and endpoint()):
        return False
    key = state["api_key"]
    merge_state(key, last_sync_attempt=time.time())
    body = payload(state, days)
    if not read_state().get("upload"):  # turned off while the ledger was reading
        return False
    rows = body["rows"]
    for i in range(0, max(len(rows), 1), 5000):
        status, res = call("POST", "/v1/usage", {**body, "rows": rows[i:i + 5000]}, key=key, timeout=30)
        if status != 200:
            break
    if status == 200:
        merge_state(key, last_sync=time.time())
        if not quiet:
            print(f"Uploaded {len(body['rows'])} day-project rows.")
        return True
    if not quiet:
        print(f"Upload failed ({status}): {res.get('error', 'no answer')}")
    return False


def cmd_sync(a):
    state = read_state()
    if not a.quiet:
        need_endpoint()
        need_key(state)
        if not state.get("upload"):
            sys.exit("Uploads are off. Turn them on with: python3 scripts/account.py upload on")
    ok = sync(state, quiet=a.quiet, days=a.days)
    sys.exit(0 if ok or a.quiet else 1)


def cmd_dashboard(a):
    need_endpoint()
    state = read_state()
    need_key(state)
    status, res = call("POST", "/v1/dashboard-link", {}, key=state["api_key"])
    if status != 200 or not res.get("url"):
        sys.exit(f"Couldn't open the dashboard ({status}): {res.get('error', 'no answer')}")
    print(f"Opening {res['url'].split('?')[0]} (the link works once, for 10 minutes).")
    webbrowser.open(res["url"])


def cmd_logout(a):
    state = read_state()
    if a.delete:
        need_endpoint()
        need_key(state)
        status, res = call("DELETE", "/v1/me", key=state["api_key"])
        if status != 200:
            sys.exit(f"Couldn't delete the account ({status}): {res.get('error', 'no answer')}. Nothing removed here.")
        print("Account and all uploaded numbers deleted.")
    for k in ("api_key", "email", "plan", "upload", "last_sync", "last_sync_attempt"):
        state.pop(k, None)
    write_state(state)
    print("Signed out on this machine.")


def main():
    ap = argparse.ArgumentParser(description="Optional free token-economy account.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("login"); p.add_argument("--upload", action="store_true"); p.set_defaults(fn=cmd_login)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("upload"); p.add_argument("state", choices=["on", "off"]); p.set_defaults(fn=cmd_upload)
    p = sub.add_parser("sync"); p.add_argument("--quiet", action="store_true"); p.add_argument("--days", type=int, default=30)
    p.set_defaults(fn=cmd_sync)
    sub.add_parser("dashboard").set_defaults(fn=cmd_dashboard)
    p = sub.add_parser("logout"); p.add_argument("--delete", action="store_true"); p.set_defaults(fn=cmd_logout)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
