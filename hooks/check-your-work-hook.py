#!/usr/bin/env python3
"""Claude Code hook that asks for the check-your-work skill, sized to the change.

Stop: if this session changed something since its last check, block the stop
once with a check brief sized to what changed:

  notes    only .md/.txt/report files changed      -> no block, no check
  local    code or config edited, nothing committed -> brief check in a Sonnet
                                                      subagent (sections 1,3,4)
  shipped  commit, push, PR, merge                  -> subagent check, sections
                                                      1,3,4,7,8
  deploy   deploy.sh, ssh, mysql, crontab, console   -> the full check, in the
                                                      main session

The brief carries the change list and the facts script's output, so the model
does not spend steps re-deriving them. It lets the stop through when the check
already ran after the last change (Skill tool, or a "Check: clean" / "Check:
found problems" / "Check: not needed" line in the last reply), when the stop is a continuation
from this hook, or when the owner's latest message says "skip the check".

PostToolUse (Bash): after a deploy.sh run, adds a note telling Claude to run the
check's deploy section now.

Never fails the session: any error lets the stop or tool result through.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _config import load  # noqa: E402

CFG = load()
SKILL = "check-your-work"
SKILL_FILE = os.path.join(CFG["plugin_root"], "skills", SKILL, "SKILL.md")
FACTS = os.path.join(CFG["plugin_root"], "scripts", "check-your-work.py")
CHECK_MODEL = CFG["check_model"]

# Paths that never count as a change: Claude's own state, scratch and temp.
IGNORED_PATHS = re.compile(r"^(" + re.escape(os.path.expanduser("~/.claude/")) + r"|/tmp/|/private/tmp/|/var/folders/|"
                           + re.escape(os.environ.get("TMPDIR", "/nonexistent")) + r")")
# Paths whose change is a note, not code: no check needed.
NOTE_PATHS = re.compile("(" + "|".join(CFG["note_paths"]) + ")", re.I)

CHANGE_TOOLS = {"Edit", "Write", "NotebookEdit"}

# Write-like MCP and app tools (Artifact publish, Docs updates, ads, droplets...).
MCP_WRITE = re.compile(
    r"(create|update|delete|batch|set_|edit|publish|activate|upload|trash|share|copy_file|"
    r"power|reboot|rebuild|resize|restore|rename|snapshot|enable|disable|droplet-action)",
    re.I,
)
MCP_READ_ONLY_SERVERS = ("mcp__ccd_turn__", "mcp__ccd_view__", "mcp__ccd_sidebar__",
                         "mcp__ccd_window__", "mcp__visualize__", "mcp__Claude_Browser__")

BASH_CHANGE = re.compile(
    r"(\bgit\s+(-C\s+(\"[^\"]*\"|\S+)\s+)?(commit|push|merge|rebase|cherry-pick|tag|rm|mv)\b"
    r"|\bgh\s+(pr|issue|release)\s+(create|merge|close|edit|comment|review)\b"
    r"|deploy\.sh|deploy-production"
    r"|\bsed\s+-i|\bperl\s+-pi"
    r"|\b(rm|mv|cp|ln|mkdir|chmod|touch|tee)\s"
    r"|\s>>?\s*(?!&|/dev/null)\S"
    r"|\bcrontab\s|\bcomposer\s+(require|update|install)|\bnpm\s+(install|i)\s|\bpod\s+install"
    r"|\bmysql\b.*\b(INSERT|UPDATE|DELETE|ALTER|CREATE|DROP)\b"
    r"|\bphp\s+\S*migrat"
    r"|xcrun\s+altool|fastlane|asc-|\bwrangler\s+(deploy|publish))",
    re.I,
)
# Changes that land outside the local file system, whatever paths appear.
REMOTE_CHANGE = re.compile(
    r"\bgit\s+(-C\s+(\"[^\"]*\"|\S+)\s+)?(commit|push|merge|rebase|cherry-pick|tag)\b"
    r"|\bgh\s+(pr|issue|release)\s+(create|merge|close|edit|comment|review)\b"
    r"|deploy\.sh|deploy-production|\bssh\s|\bmysql\b|\bcrontab\s",
    re.I,
)
SHIPPED = re.compile(
    r"\bgit\s+(-C\s+(\"[^\"]*\"|\S+)\s+)?(commit|push|merge|rebase|cherry-pick|tag)\b"
    r"|\bgh\s+(pr|issue|release)\s+(create|merge|close|edit|comment|review)\b",
    re.I,
)
PROD = re.compile(
    r"deploy\.sh|deploy-production|\bssh\s|\bmysql\b|\bcrontab\s|xcrun\s+altool|fastlane|asc-"
    r"|\bwrangler\s+(deploy|publish)|\bphp\s+\S*migrat",
    re.I,
)
# deploy.sh run as a command, not just named inside an argument.
DEPLOY = re.compile(r"(^|[;&(]\s*|\|\|\s*)(\w+=\S+\s+)*(\S*/)?deploy(\.sh|-production\S*)\b", re.M)
SKIP = re.compile(r"\b(skip|no|without)\s+(the\s+)?(check|checks|check-your-work)\b", re.I)
# "not needed" is the one-line answer when the check already ran this turn or nothing changed after
# all; without it the same changes blocked the stop again on every later turn.
REPORTED = re.compile(r"\*\*Check:\s*(clean|found problems|not needed)\*\*", re.I)
MAX_FACTS_LINES = 60


HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\1\s*(?=\n|$)", re.S)


def strip_heredocs(cmd):
    """Drop heredoc bodies so words in written text (deploy, ssh) don't classify the command."""
    return HEREDOC.sub("<<HEREDOC", cmd)


def bash_paths(cmd):
    cmd = re.sub(r"(^|[\s\"'=>])~/", lambda m: m.group(1) + os.path.expanduser("~/"), cmd)
    paths = [t.strip("'\"") for t in re.findall(r"(?:^|[\s\"'=>])(/[^\s\"';|&]+)", cmd)]
    return [t for t in paths if t != "/dev/null"]


def is_change(name, inp):
    """Return None, or a (kind, label) pair describing the change."""
    if name in CHANGE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if IGNORED_PATHS.match(path):
            return None
        return ("note" if NOTE_PATHS.search(path) else "local", f"{name} {path}")
    if name == "Bash":
        cmd = strip_heredocs(inp.get("command", ""))
        if not BASH_CHANGE.search(cmd):
            return None
        if PROD.search(cmd):
            return ("deploy", "Bash " + cmd.strip().splitlines()[0][:160])
        if SHIPPED.search(cmd):
            return ("shipped", "Bash " + cmd.strip().splitlines()[0][:160])
        paths = bash_paths(cmd)
        if paths and all(IGNORED_PATHS.match(t) for t in paths):
            return None
        kind = "note" if paths and all(NOTE_PATHS.search(t) for t in paths) else "local"
        return (kind, "Bash " + cmd.strip().splitlines()[0][:160])
    if name == "Artifact":
        if inp.get("action", "publish") in ("publish", "delete"):
            return ("shipped", f"Artifact {inp.get('action', 'publish')}")
        return None
    if name in ("ArtifactData", "CronCreate", "CronDelete", "RemoteTrigger"):
        return ("shipped", name)
    if name.startswith("mcp__") and not name.startswith(MCP_READ_ONLY_SERVERS):
        if MCP_WRITE.search(name.split("__")[-1]):
            return ("deploy", name)
    return None


def is_check(name, inp):
    """The skill run here, or a subagent launched with the check brief (it names the skill's SKILL.md)."""
    if name == "Skill":
        return inp.get("skill", "").split(":")[-1] == SKILL
    return name in ("Agent", "Task") and f"{SKILL}/SKILL.md" in str(inp.get("prompt", ""))


def agent_report(content, agent_ids):
    """True when a user entry carries a check report from a subagent: the result of an Agent call,
    or a relayed agent message. Other tool results (a file that quotes the report line) don't count."""
    if isinstance(content, str):
        return "<agent-message" in content and bool(REPORTED.search(content))
    if not isinstance(content, list):
        return False
    for b in content:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "tool_result" and b.get("tool_use_id") in agent_ids:
            inner = b.get("content")
            text = inner if isinstance(inner, str) else json.dumps(inner)
            if REPORTED.search(text.replace("\\n", "\n")):
                return True
        elif b.get("type") == "text" and agent_report(b.get("text", ""), agent_ids):
            return True
    return False


def user_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    return ""


def scan(transcript_path):
    """Return (changes since the last check, latest owner text).

    A check is the Skill tool call, a check subagent's launch, or the check's report line in a
    reply, a tool result or a relayed agent message.
    """
    changes = []
    last_user = ""
    agent_ids = set()
    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            kind = entry.get("type")
            msg = entry.get("message") or {}
            content = msg.get("content")
            if kind == "user":
                if agent_report(content, agent_ids):
                    changes = []
                text = user_text(content)
                if text and not text.lstrip().startswith("<system-reminder>"):
                    last_user = text
                    if f"<command-name>/{SKILL}" in text or f"<command-name>{SKILL}" in text:
                        changes = []
            elif kind == "assistant" and isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and REPORTED.search(block.get("text", "")):
                        changes = []
                    elif block.get("type") == "tool_use":
                        name, inp = block.get("name", ""), block.get("input") or {}
                        if name in ("Agent", "Task"):
                            agent_ids.add(block.get("id"))
                        if is_check(name, inp):
                            changes = []
                        else:
                            change = is_change(name, inp)
                            if change:
                                changes.append(change)
    return changes, last_user


def tier_of(changes):
    kinds = {k for k, _ in changes}
    for t in ("deploy", "shipped", "local", "note"):
        if t in kinds:
            return t
    return "note"


def touched_repos(changes):
    """Names of the configured repos the changes touch, or [] (meaning all) when any change names
    no repo path, such as a git commit run from the current directory."""
    repos = {name: os.path.expanduser(path).rstrip("/") + "/" for name, path in CFG["repos"].items()}
    names = set()
    for _, label in changes:
        hit = [n for n, root in repos.items() if root in label + "/"]
        if not hit:
            return []
        names.update(hit)
    return sorted(names)


def facts(prod, repos=()):
    args = ["python3", FACTS] + (["--prod"] if prod else []) + (["--repos", ",".join(repos)] if repos else [])
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=45 if prod else 12)
        text = (out.stdout or out.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"(facts script did not run: {e})"
    lines = text.splitlines()
    if len(lines) > MAX_FACTS_LINES:
        lines = lines[:MAX_FACTS_LINES] + [f"... {len(lines) - MAX_FACTS_LINES} more lines"]
    return "\n".join(lines)


def brief(tier, changes):
    seen, listed = set(), []
    for _, label in changes:
        if label not in seen:
            seen.add(label)
            listed.append(label)
    change_list = "\n".join(f"- {l}" for l in listed[:40])
    if len(listed) > 40:
        change_list += f"\n- ... {len(listed) - 40} more"
    fact_text = facts(prod=(tier == "deploy"), repos=touched_repos(changes))
    head = (f"This session changed something since its last check (tier: {tier}). "
            f"Changes since then:\n{change_list}\n\nFacts (already run, do not run again):\n{fact_text}\n\n")
    if tier == "deploy":
        return head + (
            f"Run the full {SKILL} skill here (Skill tool, skill \"{SKILL}\"), every section "
            "that applies, including section 6. Fix what it finds within the owner's request, "
            "and end with its report.")
    sections = "1, 3, 4, 7 and 8" if tier == "shipped" else "1, 3 and 4"
    return head + (
        "Do not load the skill or re-read diffs here. Launch ONE Agent (subagent_type "
        f"\"general-purpose\", model \"{CHECK_MODEL}\") with this brief: read "
        f"{SKILL_FILE} and run sections {sections} on exactly the changes listed above, "
        "using the facts given; read diffs by path, pipe test output through tail, run only the "
        "gates for the touched files, and return only the report in the skill's shape "
        "(Check: clean / found problems; Changed, Verified, Found and fixed, Not checked, Needs "
        "you), under 300 words. Pass it the change list and facts verbatim. When it returns, fix "
        "anything it found that is within the owner's request, then end with its report. "
        "If you already did that this turn, or nothing changed after all, reply with one line starting "
        "**Check: not needed** and the reason.")


def on_stop(data):
    if data.get("stop_hook_active"):
        return None
    path = data.get("transcript_path")
    if not path:
        return None
    changes, last_user = scan(path)
    if not changes or SKIP.search(last_user):
        return None
    tier = tier_of(changes)
    if tier == "note":
        return None
    return {"decision": "block", "reason": brief(tier, changes)}


def on_post_tool(data):
    inp = data.get("tool_input") or {}
    if data.get("tool_name") != "Bash" or not DEPLOY.search(inp.get("command", "")):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                "A deploy command just ran. Run the deploy section of the "
                f"{SKILL} skill now, before anything else: deployed commit and range, live "
                "assets, the application log since the deploy, scheduled jobs against the copy "
                "taken before, migrations, health on every host; then record production's commit "
                "where the project keeps deploy notes."
            ),
        }
    }


def main():
    try:
        data = json.load(sys.stdin)
        event = data.get("hook_event_name")
        out = on_stop(data) if event == "Stop" else on_post_tool(data) if event == "PostToolUse" else None
    except Exception:
        out = None
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
