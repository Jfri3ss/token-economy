#!/bin/sh
# Runs every test file and the unconfigured smoke test. Exit 1 on any failure.
set -e
cd "$(dirname "$0")/.."
export TOKEN_ECONOMY_CONFIG=/nonexistent/none.json  # tests that need a config set their own
for t in tests/test_*.py; do python3 "$t" | tail -1 | grep -q "failed: 0" || { echo "FAIL $t"; python3 "$t" | grep FAIL; exit 1; }; echo "ok $t"; done
# Unconfigured hooks must print nothing and exit 0 on ordinary events.
for h in hooks/*-hook.py; do
  out=$(echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo hi"},"cwd":"/"}' | python3 "$h") || { echo "FAIL $h exit"; exit 1; }
  [ -z "$out" ] || { echo "FAIL $h printed on a harmless event: $out"; exit 1; }
  out=$(echo 'not json' | python3 "$h") || { echo "FAIL $h exit on bad input"; exit 1; }
  [ -z "$out" ] || { echo "FAIL $h printed on bad input"; exit 1; }
  echo "ok $h quiet when unconfigured"
done
python3 -m py_compile hooks/*.py scripts/*.py && echo "ok compile"
