#!/usr/bin/env python3
"""Tests for the ledger's per-rule counts (--rules). Run: python3 tests/test_token_ledger.py"""
import importlib.util, io, json, os, sys, tempfile, contextlib
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
spec = importlib.util.spec_from_file_location("ledger", os.path.join(ROOT, "scripts", "token-ledger.py"))
ledger = importlib.util.module_from_spec(spec); spec.loader.exec_module(ledger)
failed = 0

def check(name, ok):
    global failed
    failed += not ok
    print("PASS" if ok else "FAIL", name)

def step(mid, blocks, ctx):
    return [json.dumps({"type": "assistant", "timestamp": "2026-10-28T10:00:00Z",
                        "message": {"id": mid, "content": [b], "model": "claude-opus-5-5",
                                    "usage": {"input_tokens": ctx, "output_tokens": 10}}}) for b in blocks]

def result(tid, content, error=False):
    return [json.dumps({"type": "user", "timestamp": "2026-10-28T10:00:00Z", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": error}]}})]

def bash(tid, cmd):
    return {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}

DIFF = "PreToolUse:Bash hook error: git diff with no path can be thousands of lines. Run it with --stat first, or add #full. [guard rule: git-diff]"
LOG_OLD = "PreToolUse:Bash hook error: git log without a count prints the whole history. Add -n 20 (and --oneline)."
lines = []
# 1: tagged git-diff denial, overridden in the next step with 4,000 bytes of output.
lines += step("m1", [bash("1", "git diff")], 1000) + result("1", DIFF, True)
lines += step("m2", [bash("2", "git diff #full")], 2000) + result("2", "d" * 4000)
# 2: git-diff denial inside a parallel step; the sibling call written after the denial is not the retry.
lines += step("m3", [bash("3", "git diff")], 3000) + result("3", DIFF, True)
lines += step("m3", [bash("4", "echo sibling")], 3000) + result("4", "sibling")
lines += step("m4", [bash("5", "git diff --stat")], 4000) + result("5", "s" * 400)
# 3: second git-diff override, so the rule has two full-size samples.
lines += step("m5", [bash("6", "git diff")], 5000) + result("6", DIFF, True)
lines += step("m6", [bash("7", "git diff #full")], 6000) + result("7", "d" * 4000)
# 4: untagged denial from an older guard is still attributed by its wording.
lines += step("m7", [bash("8", "git log")], 7000) + result("8", LOG_OLD, True)
lines += step("m8", [bash("9", "git log -n 5")], 8000) + result("9", "c" * 100)
lines += step("m9", [{"type": "text", "text": "done"}], 9000)
d = tempfile.mkdtemp(); path = os.path.join(d, "s.jsonl")
open(path, "w").write("\n".join(lines) + "\n")
r = ledger.session(path)
g, l = r["rules"].get("git-diff", {}), r["rules"].get("git-log", {})

check("tagged denials count per rule", g.get("denials") == 3 and g.get("overrides") == 2)
check("session totals still match", r["counts"]["denials"] == 4 and r["counts"]["overrides"] == 2)
check("cost is the context of the step after each denial, not the sibling", g.get("retry_ctx") == 2000 + 4000 + 6000)
check("override output is sized", g.get("full_n") == 2 and g.get("full_bytes") == 8000)
check("retry is the next step's call, with the steps still to come", g.get("retries") == [(400, 5)])
check("untagged wording maps to its rule", l.get("denials") == 1 and l.get("retries") == [(100, 1)])
check("unknown wording is 'other'", ledger.guard_rule("PreToolUse: something new") == "other")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ledger.rule_table([r])
out = buf.getvalue()
row = next((x for x in out.splitlines() if x.startswith("git-diff")), "")
# 2 of 3 overridden; saved = (4000 - 400) / 4 tokens * 5 later steps = 4,500 tokens, cost 12,000.
check("table flags a mostly overridden rule and prints its cost", " 0.01 " in row and "review: mostly overridden" in row)
check("table marks thin rules", "too few to judge" in next((x for x in out.splitlines() if x.startswith("git-log")), ""))
print("failed:", failed); sys.exit(1 if failed else 0)
