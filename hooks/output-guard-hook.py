#!/usr/bin/env python3
"""PreToolUse hook that keeps large tool output out of the context window.

Every byte a tool returns is re-sent on every later model step, so a 2,000-line
file read once costs its size hundreds of times. This hook refuses the few
command shapes that produce that kind of output and names the smaller form:

  Read of a file over MAX_LINES with no offset/limit      -> read a range
  cat <one file> over MAX_LINES, not piped                 -> sed -n 'a,bp' / grep
  git diff / git show with no path and no --stat           -> --stat first
  git log with no count                                    -> -n 20 --oneline
  test, lint, type-check or build runs with no tail/grep   -> 2>&1 | tail -40
  find / ls -R / tree with no head                         -> | head -50

Escape hatch: put "#full" anywhere in the command, or pass allow_large to Read.
Never fails the session: any error lets the call through.
"""
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _config import load  # noqa: E402

MAX_LINES = int(load()["max_lines"])
# A test, lint, type-check or build command at the start of a simple command (env assignments allowed).
TEST_CMDS = re.compile(
    r"^(?:\w+=\S*\s+)*(?:npx\s+(?:jest|tsc|eslint)\b|npm\s+(?:test|run\s+(?:lint|test|build))\b|phpunit\b|"
    r"\S*vendor/bin/phpunit\b|xcodebuild\b|\.?/?gradlew?\b|python3?\s+-m\s+pytest\b|pytest\b|pod\s+install\b)",
    re.I,
)
QUOTED = re.compile(r"\"(?:[^\"\\\\]|\\\\.)*\"|'[^']*'")
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\1\s*(?=\n|$)", re.S)
TRIM = re.compile(r"\|\s*(tail|head|grep|wc|sed|awk|rg|xcpretty|xcbeautify|jq|sort|uniq|cut|python3)\b|\s>\s*\S|\s2>&1\s*>\s*\S")


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def count_lines(path, cwd):
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return None


def check_read(inp):
    if inp.get("limit") or inp.get("offset") or inp.get("allow_large"):
        return None
    path = inp.get("file_path", "")
    if re.search(r"\.(png|jpe?g|gif|pdf|ipynb|webp)$", path, re.I):
        return None
    n = count_lines(path, None)
    if n and n > MAX_LINES:
        return deny(f"{os.path.basename(path)} has {n} lines. Read the part you need with offset and "
                    f"limit, or grep for the symbol first; pass allow_large only if you truly need all of it.")
    return None


def check_bash(cmd, cwd):
    if "#full" in cmd:
        return None
    first = cmd.strip()
    # cat of one file, not piped, no heredoc, no redirect.
    m = re.match(r"^cat\s+(?:-[a-zA-Z]+\s+)*(\"[^\"]+\"|'[^']+'|[^\s|<>;&]+)\s*$", first)
    if m:
        n = count_lines(m.group(1).strip("'\""), cwd)
        if n and n > MAX_LINES:
            return deny(f"That file has {n} lines. Read a range (sed -n 'a,bp'), grep for what you need, "
                        f"or add #full if the whole file is really needed.")
    # Each simple command in the line, with heredoc bodies and quoted text removed first so
    # words inside a commit message or a grep pattern never count as commands.
    bare = QUOTED.sub('""', HEREDOC.sub("<<HEREDOC", cmd))
    for part in re.split(r"\|\||&&|;|\n", bare):
        seg = part.strip()
        g = re.match(r"^git\s+(?:-C\s+(?:\"[^\"]*\"|\S+)\s+)?(?:--no-pager\s+)?(diff|show|log)\b(.*)$", seg, re.S)
        if g:
            sub, rest = g.group(1), g.group(2)
            if "|" in rest:
                continue
            try:
                toks = shlex.split(rest)
            except ValueError:
                toks = rest.split()
            if sub in ("diff", "show"):
                has_stat = any(t.startswith(("--stat", "--shortstat", "--numstat", "--name-only",
                                             "--name-status", "--format", "--pretty", "-s")) for t in toks)
                has_path = any(not t.startswith("-") and t != '""' for t in toks)
                if not has_stat and not has_path and sub == "diff":
                    return deny("git diff with no path can be thousands of lines. Run it with --stat first, "
                                "then diff the paths you need (git diff -- path), or add #full.")
                if not has_stat and not has_path and sub == "show" and not any(t.startswith("-") for t in toks):
                    return deny("git show of a whole commit can be huge. Use git show --stat <commit> first, "
                                "then show -- path, or add #full.")
            if sub == "log":
                limited = any(re.match(r"^-\d+$|^-n$|^--max-count|^-n\d+$|^--since|^--after|^-L", t) or ".." in t
                              for t in toks) or "--oneline" in toks
                if not limited:
                    return deny("git log without a count prints the whole history. Add -n 20 (and --oneline).")
        if TEST_CMDS.search(seg) and not TRIM.search(seg):
            return deny("Test, lint, type-check and build output is long and stays in context. Append "
                        "`2>&1 | tail -40` (or grep for FAIL/error), or add #full.")
        if (re.match(r"^(find\s|ls\s+-[a-zA-Z]*R|tree\b)", seg) and not TRIM.search(seg)
                and not re.search(r"-maxdepth\s+[12]\b|-exec\b|-delete\b|-L\s*[12]\b", seg)):
            return deny("That listing can be very long. Pipe it through | head -50 or narrow it, or add #full.")
    return None


def main():
    try:
        data = json.load(sys.stdin)
        name, inp = data.get("tool_name"), data.get("tool_input") or {}
        out = None
        if name == "Read":
            out = check_read(inp)
        elif name == "Bash":
            out = check_bash(inp.get("command", ""), data.get("cwd"))
    except Exception:
        out = None
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
