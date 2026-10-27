#!/bin/sh
# Runs every test file and the unconfigured smoke test. Exit 1 on any failure.
set -e
cd "$(dirname "$0")/.."
export TOKEN_ECONOMY_CONFIG=/nonexistent/none.json  # tests that need a config set their own
export TOKEN_ECONOMY_ENDPOINT=off  # never reach the live account server
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
# Account server (needs Node 22.5+ for node:sqlite).
if command -v node >/dev/null 2>&1; then
  node tests/test_server.mjs | tail -1 | grep -q "failed: 0" || { echo "FAIL tests/test_server.mjs"; node tests/test_server.mjs | grep FAIL; exit 1; }
  echo "ok tests/test_server.mjs"
else
  echo "skip tests/test_server.mjs (no node)"
fi
