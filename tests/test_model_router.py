#!/usr/bin/env python3
"""Tests for model-router-hook.py. Run: python3 tests/test_model_router.py"""
import json, os, subprocess, sys, importlib.util, tempfile
HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "model-router-hook.py")
# A config with domain words, to prove hard_words are read; the generic rules are tested without them.
cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
json.dump({"hard_words": ["payout", "refund"]}, cfg); cfg.close()
os.environ["TOKEN_ECONOMY_CONFIG"] = cfg.name
spec = importlib.util.spec_from_file_location("router", HOOK); r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)

TIERS = [
    ("What does the payout hold do for new sellers?", "hard"),
    ("Why is the balance endpoint returning 500?", "hard"),
    ("Fix the refund flow so partial refunds work", "hard"),
    ("Change the auth token refresh so it cannot deadlock", "hard"),
    ("Add a migration for the new table", "hard"),
    ("Find every file that calls balance.php", "read"),
    ("List the open PRs on the server repo", "read"),
    ("Fix the typo in OPEN-TODOS.md", "routine"),
    ("Update the README wording for the monitor", "routine"),
    ("Add a CSV export button to the Activity sheet", "build"),
    ("Is the UK sign-up still paused?", "question"),
    ("How many users signed up this week?", "read"),
    ("do it", "continue"),
    ("Yes, merge CultivateMobile PR #307.", "continue"),
    ("ok", "continue"),
]
failed = 0
for p, want in TIERS:
    got = r.classify(p); ok = got == want; failed += not ok
    print("PASS" if ok else "FAIL", f"{p[:50]!r} -> {got}")

def agent(inp):
    out = subprocess.run([sys.executable, HOOK], input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": inp}),
                         capture_output=True, text=True)
    return bool(out.stdout.strip())
AGENTS = [
    ("read brief no model -> deny", {"prompt": "Search the server for every caller of PayoutHoldService", "description": "find callers"}, True),
    ("read brief haiku -> allow", {"prompt": "Search the server for every caller of PayoutHoldService", "model": "haiku"}, False),
    ("review brief sonnet -> allow", {"prompt": "Review this diff for bugs and run the tests", "model": "sonnet"}, False),
    ("hard brief haiku -> deny", {"prompt": "Design the auth refresh flow and decide how the schema changes", "model": "haiku"}, True),
    ("hard brief top model -> allow", {"prompt": "Design the auth refresh flow and decide how the schema changes", "model": "opus"}, False),
    ("fork -> allow", {"prompt": "Review everything we did", "subagent_type": "fork"}, False),
]
for name, inp, want in AGENTS:
    got = agent(inp); ok = got == want; failed += not ok
    print("PASS" if ok else "FAIL", name)
os.unlink(cfg.name)
print("failed:", failed); sys.exit(1 if failed else 0)
