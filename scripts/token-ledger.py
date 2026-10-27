#!/usr/bin/env python3
"""Token ledger: where the sessions' tokens went. Read-only.

    python3 scripts/token-ledger.py [--last N] [--days D] [--top] [--project DIR]
    python3 scripts/token-ledger.py --compare YYYY-MM-DD [--days D] [--project DIR]

Reads the transcripts Claude Code keeps under ~/.claude/projects/ for the
project (default: $CLAUDE_PROJECT_DIR or the current directory).

Per session: model, steps (assistant messages), context tokens re-read, output
tokens, context size at the end, tool-result KB, check-hook blocks, check runs,
guard denials, guard overrides (a denial followed straight away by the same call
with #full or allow_large), routing tiers. --top lists the largest tool results.

--compare splits the sessions at a date (say, the day you installed the plugin)
and prints per-session medians before and after, as rates per step, so a week of
long sessions doesn't look worse than a week of short ones just for its size.
"""
import argparse
import collections
import glob
import json
import os
import re
import statistics
import time

# Text that only the output guard's deny reasons contain.
GUARD_MARKS = ("or add #full", "pass allow_large only if", "prints the whole history")
CHECK_BLOCK = "changed something since its last check"
COUNTS = ("steps", "reread", "out_tokens", "tool_bytes", "blocks", "checks", "denials", "overrides")


def project_transcripts(project_dir):
    """Claude Code names a project's transcript folder after its path, non-alphanumerics replaced by '-'."""
    encoded = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(os.path.expanduser(project_dir)))
    return os.path.expanduser(os.path.join("~/.claude/projects", encoded))


def is_override(name, inp):
    return (name == "Bash" and "#full" in str(inp.get("command", ""))) or (name == "Read" and bool(inp.get("allow_large")))


def session(path, top=False):
    """One transcript's totals, plus the same counts bucketed by UTC day for rollups."""
    s = collections.Counter()
    days = collections.defaultdict(collections.Counter)
    ids = {}
    biggest = []
    tiers = collections.Counter()
    models = collections.Counter()
    title = ""
    last_ctx = 0
    first_day = ""
    denied_tool = None  # tool name of a denial not yet followed by another call

    def add(day, key, n=1):
        s[key] += n
        days[day][key] += n

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            day = (e.get("timestamp") or "")[:10] or "unknown"
            if day != "unknown" and not first_day:
                first_day = day
            kind = e.get("type")
            m = e.get("message") or {}
            c = m.get("content") if isinstance(m, dict) else None
            if kind == "assistant" and isinstance(c, list):
                add(day, "steps")
                u = m.get("usage") or {}
                ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                add(day, "reread", ctx)
                last_ctx = ctx or last_ctx
                add(day, "out_tokens", u.get("output_tokens", 0))
                model = m.get("model") or ""
                models[model.split("-")[1] if "-" in model else "?"] += 1
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        name, inp = b.get("name"), b.get("input") or {}
                        ids[b.get("id")] = name
                        if name == "Skill" and "check-your-work" in str(inp):
                            add(day, "checks")
                        if denied_tool is not None:
                            if name == denied_tool and isinstance(inp, dict) and is_override(name, inp):
                                add(day, "overrides")
                            denied_tool = None
                if not any(isinstance(b, dict) and b.get("type") == "tool_use" for b in c):
                    denied_tool = None  # an override has to be the very next call
            elif kind == "user":
                if isinstance(c, str):
                    if not title and not c.startswith("<"):
                        title = c.strip().splitlines()[0][:48] if c.strip() else ""
                    if CHECK_BLOCK in c:
                        add(day, "blocks")
                elif isinstance(c, list):
                    for b in c:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text":
                            t = b.get("text", "")
                            if not title and t.strip() and not t.startswith("<"):
                                title = t.strip().splitlines()[0][:48]
                            if CHECK_BLOCK in t:
                                add(day, "blocks")
                            if t.startswith("Routing: "):
                                tiers[t.split(".")[0][9:].split(" ")[0]] += 1
                        if b.get("type") == "tool_result":
                            r = b.get("content")
                            r = r if isinstance(r, str) else json.dumps(r)
                            n = ids.get(b.get("tool_use_id"), "?")
                            add(day, "tool_bytes", len(r))
                            if b.get("is_error") and r.startswith("PreToolUse:") and any(g in r for g in GUARD_MARKS):
                                add(day, "denials")
                                denied_tool = n
                            if top:
                                biggest.append((len(r) / 1024, n, r[:70].replace("\n", " ")))
    return {"file": os.path.basename(path)[:8], "title": title, "first_day": first_day, "counts": s, "days": days,
            "ctx_k": last_ctx / 1e3, "tiers": tiers, "models": models,
            "biggest": sorted(biggest, reverse=True)[:8], "mtime": os.path.getmtime(path)}


def rollup(since_days=30, root="~/.claude/projects"):
    """Per-day totals across every project on this machine: {day: {project_folder: Counter}}.

    Only counts leave this function: no titles, prompts, paths inside the project, or tool output.
    """
    cutoff = time.time() - since_days * 86400
    oldest = time.strftime("%Y-%m-%d", time.gmtime(cutoff))
    out = collections.defaultdict(dict)
    for folder in sorted(glob.glob(os.path.join(os.path.expanduser(root), "*"))):
        for path in glob.glob(os.path.join(folder, "*.jsonl")):
            if os.path.getmtime(path) < cutoff:
                continue
            for day, counts in session(path)["days"].items():
                if day == "unknown" or day < oldest:
                    continue
                agg = out[day].setdefault(os.path.basename(folder), collections.Counter())
                agg.update(counts)
                agg["sessions"] += 1
    return out


def pooled(rows):
    """Rates over all steps of a group of sessions, so each step (what you pay for) counts once."""
    c = collections.Counter()
    for r in rows:
        c.update(r["counts"])
    steps = c["steps"] or 1
    return {"sessions": len(rows), "steps_median": statistics.median([r["counts"]["steps"] for r in rows]) if rows else 0,
            "ctx_k_per_step": c["reread"] / steps / 1e3, "tool_kb_per_step": c["tool_bytes"] / steps / 1024,
            "out_per_step": c["out_tokens"] / steps, "denials_per_100": 100 * c["denials"] / steps,
            "denials": c["denials"], "overrides": c["overrides"]}


def compare(rows, split):
    before = pooled([r for r in rows if r["first_day"] and r["first_day"] < split and r["counts"]["steps"]])
    after = pooled([r for r in rows if r["first_day"] and r["first_day"] >= split and r["counts"]["steps"]])
    print(f"Split at {split}: {before['sessions']} sessions before, {after['sessions']} after. Rates are over all steps.\n")
    print(f"{'measure':30} {'before':>10} {'after':>10} {'change':>8}")
    labels = [("steps_median", "median steps per session"), ("ctx_k_per_step", "context K per step"),
              ("tool_kb_per_step", "tool output KB per step"), ("out_per_step", "output tokens per step"),
              ("denials_per_100", "guard denials per 100 steps")]
    for key, label in labels:
        b, a = before[key], after[key]
        ch = f"{(a - b) / b * 100:+.0f}%" if b else ""
        print(f"{label:30} {b:10.1f} {a:10.1f} {ch:>8}")
    for name, g in (("before", before), ("after", after)):
        if g["denials"]:
            print(f"\nOverride rate {name}: {g['overrides']} of {g['denials']} denials "
                  f"({g['overrides'] / g['denials'] * 100:.0f}%) were rerun as written with #full or allow_large.")
    print("\nContext per step is the main cost. The work itself differs between the two periods (long builds vs"
          "\nshort scheduled runs move every number), so treat a change as real only when it holds over several"
          "\nweeks of similar work.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=8)
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--top", action="store_true")
    ap.add_argument("--compare", metavar="YYYY-MM-DD", default=None)
    ap.add_argument("--project", default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    a = ap.parse_args()
    folder = project_transcripts(a.project)
    files = sorted(glob.glob(os.path.join(folder, "*.jsonl")), key=os.path.getmtime)
    if not files:
        print(f"no transcripts found in {folder}")
        return
    if a.days:
        files = [f for f in files if os.path.getmtime(f) > time.time() - a.days * 86400]
    if a.compare:
        compare([session(f) for f in files], a.compare)
        return
    files = files[-a.last:]
    rows = [session(f, a.top) for f in files]
    print(f"{'session':8} {'date':10} {'model':7} {'steps':>5} {'reread M':>9} {'out K':>6} {'ctx K':>6} {'tool KB':>7} "
          f"{'blk':>3} {'chk':>3} {'den':>3} {'ovr':>3}  title")
    tot = collections.Counter()
    for r in rows:
        c = r["counts"]
        model = r["models"].most_common(1)[0][0] if r["models"] else "?"
        date = time.strftime("%Y-%m-%d", time.localtime(r["mtime"]))
        print(f"{r['file']:8} {date:10} {model:7} {c['steps']:5d} {c['reread'] / 1e6:9.1f} {c['out_tokens'] / 1e3:6.0f} "
              f"{r['ctx_k']:6.0f} {c['tool_bytes'] / 1024:7.0f} {c['blocks']:3d} {c['checks']:3d} {c['denials']:3d} "
              f"{c['overrides']:3d}  {r['title']}")
        tot.update(c)
        if r["tiers"]:
            print(f"{'':8} routing: " + ", ".join(f"{k} {v}" for k, v in r["tiers"].most_common()))
        if a.top and r["biggest"]:
            for kb, n, head in r["biggest"][:5]:
                print(f"{'':8}   {kb:7.0f} KB {n:24} {head}")
    print(f"{'total':8} {'':10} {'':7} {tot['steps']:5d} {tot['reread'] / 1e6:9.1f} {tot['out_tokens'] / 1e3:6.0f} {'':6} "
          f"{tot['tool_bytes'] / 1024:7.0f} {tot['blocks']:3d} {tot['checks']:3d} {tot['denials']:3d} {tot['overrides']:3d}")
    print("\nreread M = million context tokens re-sent across all steps (the real cost); ctx K = context size at the end;"
          "\nblk = check-hook blocks, chk = check skill runs, den = output-guard denials,"
          "\novr = denials rerun as written with #full or allow_large (a likely false positive).")


if __name__ == "__main__":
    main()
