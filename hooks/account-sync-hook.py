#!/usr/bin/env python3
"""SessionStart hook: at most once a day, upload the summary numbers in the background.

Does nothing unless you signed in with scripts/account.py and turned uploads on. Never prints,
never waits on the network, never fails the session: the upload runs as a detached process.
"""
import json
import os
import subprocess
import sys
import time

STATE = os.path.expanduser("~/.claude/token-economy/account.json")
EVERY = 20 * 3600


def main():
    try:
        event = json.loads(sys.stdin.read() or "{}")
        if not isinstance(event, dict) or event.get("hook_event_name") != "SessionStart":
            return 0
        with open(STATE, encoding="utf-8") as f:
            state = json.load(f)
        if not (isinstance(state, dict) and state.get("api_key") and state.get("upload")):
            return 0
        if time.time() - max(state.get("last_sync") or 0, state.get("last_sync_attempt") or 0) < EVERY:
            return 0
        # Record the attempt here, so a sync that can't run (no endpoint, offline) still waits a day.
        # Re-read first and write only if the same key is still signed in, so a logout isn't undone.
        key = state["api_key"]
        with open(STATE, encoding="utf-8") as f:
            state = json.load(f)
        if not (isinstance(state, dict) and state.get("api_key") == key and state.get("upload")):
            return 0
        state["last_sync_attempt"] = time.time()
        tmp = f"{STATE}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE)
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "account.py")
        subprocess.Popen([sys.executable, script, "sync", "--quiet"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
