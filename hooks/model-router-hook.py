#!/usr/bin/env python3
"""Routes each task to the cheapest model that can do it well.

A session cannot change its own model (the app refuses it), but the Agent tool
takes a model and so does start_session. So the switch happens per task: this
hook classifies the owner's prompt and the session's current model, and adds
one line of context telling the session where the heavy part should run.

UserPromptSubmit: classify the prompt -> tier (question, read, routine, hard,
build) and inject the routing line from docs/MODEL-ROUTING.md.

PreToolUse (Agent): refuse an Agent call whose model does not fit its brief:
read, search, test and review briefs must run on haiku or sonnet; payments,
auth, schema, deploy and design briefs must not run on haiku.

Never fails the session: any error lets the prompt or call through.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _config import load  # noqa: E402

CFG = load()

CHEAP = ("haiku", "sonnet")
TOP = ("fable", "opus")

# Plain "token", "session", "table", "index", "release" and "terms" sent everyday prompts ("the token
# usage program", "this session") to the hard tier; they count only in the pairings below.
HARD_WORDS = [
    "auth\\w*", "(access|refresh|api|jwt|bearer|csrf) tokens?", "session (cookie|expiry|fixation|hijack\\w*)s?",
    "security", "secret", "permission", "migration", "schema", "(db|database|sql) (table|index)(es|s)?",
    "deploy", "production", "prod", "architect", "design", "redesign", "refactor", "debug", "crash\\w*",
    "race", "deadlock", "concurren\\w*", "incident", "outage", "root cause", "contract", "api change",
    "legal", "privacy", "error", "fail\\w*", "broken", "not working", "bug", "5\\d\\d", "regression",
    "why (does|is|did) .{0,40}(fail|break|crash|wrong)",
]
HARD = re.compile(r"\b(" + "|".join(HARD_WORDS + [re.escape(w) for w in CFG["hard_words"]]) + r")\b", re.I)
# The owner's own hard_words make any question hard (how a payout hold works must be answered with care);
# the generic words make a question hard only when it asks why something fails.
DOMAIN = re.compile(r"\b(" + "|".join(re.escape(w) for w in CFG["hard_words"]) + r")\b", re.I) if CFG["hard_words"] else None
DIAGNOSTIC = re.compile(r"\b(why|fail\w*|broken|not working|crash\w*|error|bug|wrong|5\d\d|5xx)\b", re.I)
READ = re.compile(
    r"^(find|where|which files?|list|search|look up|look for|show me|summari[sz]e|read|review|audit|compare|"
    r"what('s| is) open|status of|how many|count|grep|trace|inventory|map out|survey)\b", re.I)
ROUTINE = re.compile(
    r"\b(typo|rename|wording|copy|comment|docs?\b|readme|changelog|todo|memory|bump|version|label|string|"
    r"log line|lint|format|whitespace|\.md\b|note|checklist|spelling)\b", re.I)
ACTION = re.compile(
    r"\b(fix|add|change|build|write|implement|create|update|remove|delete|make|refactor|move|rename|"
    r"ship|deploy|merge|commit|push|run|set|switch|turn|wire|bump|edit|replace|convert|migrate)\b", re.I)
QUESTION = re.compile(r"^(what|why|how|is|are|can|could|does|do|did|should|would|will|which|who|when|where)\b", re.I)


SHORT_GO = re.compile(r"^(do it|go|go ahead|yes|ok(ay)?|sure|proceed|continue|carry on|ship it|merge it|"
                      r"yes,? .{0,60}|please do|make it so|all of (it|them)|both|that one|"
                      r"do (it|all|both|them|these|those|that|this|all of (it|them)|#?\d[\d\s,&+–-]*(and #?\d+)?)"
                      r"( (here|now|too|please))?)[.!]?$", re.I)


def classify(prompt):
    p = prompt.strip()
    if len(p.split()) <= 6 and SHORT_GO.match(p):
        return "continue"
    if HARD.search(p) and (ACTION.search(p) or (QUESTION.search(p) and (DIAGNOSTIC.search(p) or (DOMAIN and DOMAIN.search(p))))):
        return "hard"
    if READ.search(p) and not re.search(r"\b(fix|change|edit|build|write|implement)\b", p, re.I):
        return "read"
    if QUESTION.search(p) and not ACTION.search(p):
        return "question"
    if ACTION.search(p) and ROUTINE.search(p) and len(p) < 600:
        return "routine"
    if ACTION.search(p):
        return "build"
    return "question" if "?" in p else "build"


def family(model):
    m = (model or "").lower()
    for f in ("haiku", "sonnet", "opus", "fable"):
        if f in m:
            return f
    return "unknown"


def configured_model():
    """The model the session starts on, for the first prompt, before the transcript names one."""
    if os.environ.get("ANTHROPIC_MODEL"):
        return os.environ["ANTHROPIC_MODEL"]
    for path in (os.path.join(CFG.get("project_dir") or os.getcwd(), ".claude", "settings.local.json"),
                 os.path.join(CFG.get("project_dir") or os.getcwd(), ".claude", "settings.json"),
                 os.path.expanduser("~/.claude/settings.json")):
        try:
            with open(path, encoding="utf-8") as f:
                model = json.load(f).get("model")
        except (OSError, ValueError, AttributeError):
            continue
        if model:
            return model
    return None


def session_model(transcript_path):
    if not transcript_path:
        return configured_model()
    model = None
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                if '"model"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") == "assistant":
                    model = (e.get("message") or {}).get("model") or model
    except OSError:
        return configured_model()
    return model or configured_model()


def route(tier, fam):
    on_top = fam in TOP
    # Unknown model: give advice that holds on any model rather than guess it is a cheap one and send
    # a one-line question to a top-model Agent.
    known = fam != "unknown"
    if tier == "continue":
        return "Routing: go-ahead on the task already in hand; keep its routing and do it."
    if tier == "question":
        return ("Routing: question. Answer from what you know plus at most one grep. No subagents, no edits, "
                "no file reads beyond a range.")
    if tier == "read":
        return ("Routing: read-only task. Delegate the reading to ONE Agent on haiku (sonnet if it must weigh "
                "evidence) with a narrow brief, and relay its answer. Do not read the files in this context.")
    if tier == "routine":
        if on_top:
            return ("Routing: routine edit on a top model. Hand the edit to ONE Agent on sonnet with the exact "
                    "files and wording, then check its diff by path and report. Keep your own steps to three.")
        return "Routing: routine edit. Do it here directly; read by range, no subagents needed."
    if tier == "hard":
        if on_top or not known:
            return ("Routing: hard task (payments, auth, schema, deploy, design or diagnosis). Do the thinking "
                    "here; send reads, searches and test runs to sonnet or haiku Agents and keep their output "
                    "out of this context.")
        return ("Routing: hard task on a cheaper model. Do the diagnosis or design step in ONE Agent on fable "
                "with the full brief, then implement its answer here and run the gates. Say in one line that "
                "you did so.")
    # build
    if on_top:
        return ("Routing: build task. Do the design and the delicate edits here; send wide reads, searches and "
                "test suites to sonnet or haiku Agents. Batch independent tool calls in one step.")
    return "Routing: build task. Do it here; use haiku Agents for wide reads and keep test output to a tail."


def on_prompt(data):
    prompt = data.get("prompt") or ""
    if not prompt.strip() or prompt.lstrip().startswith(("/", "<")) or len(prompt) > 6000:
        return None
    tier = classify(prompt)
    fam = family(session_model(data.get("transcript_path")))
    line = route(tier, fam)
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": f"{line} (model: {fam}; matrix: MODEL-ROUTING.md in the token-economy plugin)"}}


READ_BRIEF = re.compile(
    r"\b(read|search|find|grep|list|locate|explore|inventory|trace|audit|review|summari[sz]e|run (the )?tests?|"
    r"run (the )?(suite|gates)|check (that|whether|if)|verify|compare)\b", re.I)


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def on_agent(data):
    inp = data.get("tool_input") or {}
    if inp.get("subagent_type") == "fork":
        return None
    model = family(inp.get("model"))
    brief = (inp.get("prompt") or "") + " " + (inp.get("description") or "")
    hard = HARD.search(brief) and re.search(r"\b(design|decide|diagnose|fix|implement|change|write)\b", brief, re.I)
    if model == "haiku" and hard:
        return deny("This brief needs judgment on payments, auth, schema, deploy or design. Run it on sonnet "
                    "or fable, not haiku.")
    if model in ("unknown", "opus", "fable") and READ_BRIEF.search(brief) and not hard:
        want = "haiku" if inp.get("subagent_type") == "Explore" or not re.search(r"\b(review|audit|verify|judge)\b", brief, re.I) else "sonnet"
        return deny(f"A read, search, test or review brief does not need a top model. Pass model \"{want}\" "
                    "(see MODEL-ROUTING.md in the token-economy plugin).")
    return None


def main():
    try:
        data = json.load(sys.stdin)
        event = data.get("hook_event_name")
        if event == "UserPromptSubmit":
            out = on_prompt(data)
        elif event == "PreToolUse" and data.get("tool_name") == "Agent":
            out = on_agent(data)
        else:
            out = None
    except Exception:
        out = None
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
