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

A bare git log or listing that is one simple read-only command on relative paths is
rewritten instead of refused (-n 20 / | head -50 added, with a note saying so), which saves
the extra round trip a refusal costs. The rewrite has to be returned with "allow", which
skips the permission prompt, so it is limited to commands that only read inside the
working directory; test and build runs execute code and are still refused.

Escape hatch: put "#full" anywhere in the command, or pass allow_large to Read.
Each reason ends with [guard rule: <id>] so the ledger's --rules table can tell which
rules get overridden most.
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


def deny(reason, rule):
    # The [guard rule: ...] tag lets the ledger count denials and overrides per rule.
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": f"{reason} [guard rule: {rule}]"}}


def rewrite(inp, command, note, rule):
    # The [guard rewrite: ...] tag marks it in the transcript, like the deny tag.
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                   "permissionDecisionReason": f"{note} [guard rewrite: {rule}]",
                                   "updatedInput": dict(inp, command=command),
                                   "additionalContext": f"{note} [guard rewrite: {rule}]"}}


# A rewrite is auto-approved, so it is allowed only for a command built from plain characters (no
# expansion, escapes, chaining, redirects or comments), with no absolute, home or parent path, no
# unquoted glob, and no flag that writes, runs a program or follows links out of the project.
REWRITE_CHARS = re.compile(r"^[\w ./@=,:%+'*?-]+$")
UNSAFE_FLAG = {
    "find": re.compile(r"^-(exec\w*|ok\w*|delete|fprint\w*|fls|L|H|follow|files0-from)$"),
    "ls": re.compile(r"^(--.*|-\S*L\S*)$"),
    "git": re.compile(r"^--(o|e|t)"),  # --output, --ext-diff, --textconv, --exec and their abbreviations
}


def rewrite_tokens(cmd, prog):
    """The command's words when it is safe to rewrite and auto-approve, else None."""
    if not REWRITE_CHARS.match(cmd):
        return None
    unquoted = re.sub(r"'[^']*'", "", cmd)
    if "'" in unquoted or "*" in unquoted or "?" in unquoted or (prog == "git" and "'" in cmd):
        return None
    try:
        toks = shlex.split(cmd)
    except ValueError:
        return None
    if toks[0] != prog:
        return None
    for t in toks[1:]:
        if t.startswith(("/", "~")) or ".." in t or UNSAFE_FLAG[prog].match(t):
            return None
    return toks


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
                    f"limit, or grep for the symbol first; pass allow_large only if you truly need all of it.", "read-large")
    return None


def check_bash(cmd, cwd, inp=None):
    if "#full" in cmd:
        return None
    first = cmd.strip()
    # cat of one file, not piped, no heredoc, no redirect.
    m = re.match(r"^cat\s+(?:-[a-zA-Z]+\s+)*(\"[^\"]+\"|'[^']+'|[^\s|<>;&]+)\s*$", first)
    if m:
        n = count_lines(m.group(1).strip("'\""), cwd)
        if n and n > MAX_LINES:
            return deny(f"That file has {n} lines. Read a range (sed -n 'a,bp'), grep for what you need, "
                        f"or add #full if the whole file is really needed.", "cat-large")
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
                                "then diff the paths you need (git diff -- path), or add #full.", "git-diff")
                if not has_stat and not has_path and sub == "show" and not any(t.startswith("-") for t in toks):
                    return deny("git show of a whole commit can be huge. Use git show --stat <commit> first, "
                                "then show -- path, or add #full.", "git-show")
            if sub == "log":
                limited = any(re.match(r"^-\d+$|^-n$|^--max-count|^-n\d+$|^--since|^--after|^-L", t) or ".." in t
                              for t in toks) or "--oneline" in toks
                if not limited:
                    raw = cmd.strip()
                    if inp is not None and seg == raw and rewrite_tokens(raw, "git"):
                        # No quotes in raw, so seg is raw and the match offsets apply to it.
                        new = raw[:g.end(1)] + " -n 20" + raw[g.end(1):]
                        return rewrite(inp, new, "git log had no count, so -n 20 was added; "
                                       "ask for more with -n or a range, or add #full.", "git-log")
                    return deny("git log without a count prints the whole history. Add -n 20 (and --oneline).", "git-log")
        if TEST_CMDS.search(seg) and not TRIM.search(seg):
            return deny("Test, lint, type-check and build output is long and stays in context. Append "
                        "`2>&1 | tail -40` (or grep for FAIL/error), or add #full.", "test-output")
        if (re.match(r"^(find\s|ls\s+-[a-zA-Z]*R|tree\b)", seg) and not TRIM.search(seg)
                and not re.search(r"-maxdepth\s+[12]\b|-exec\b|-delete\b|-L\s*[12]\b", seg)):
            prog = seg.split()[0]
            if inp is not None and prog in ("find", "ls") and seg == bare.strip() and rewrite_tokens(cmd.strip(), prog):
                return rewrite(inp, cmd.strip() + " | head -50", "The listing was piped through head -50; "
                               "narrow it or add #full to see everything.", "listing")
            return deny("That listing can be very long. Pipe it through | head -50 or narrow it, or add #full.", "listing")
    return None


def main():
    try:
        data = json.load(sys.stdin)
        name, inp = data.get("tool_name"), data.get("tool_input") or {}
        out = None
        if name == "Read":
            out = check_read(inp)
        elif name == "Bash":
            out = check_bash(inp.get("command", ""), data.get("cwd"), inp)
    except Exception:
        out = None
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
