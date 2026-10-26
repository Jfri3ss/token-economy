#!/usr/bin/env python3
"""Token ledger: where the sessions' tokens went. Read-only.

    python3 scripts/token-ledger.py [--last N] [--days D] [--top] [--project DIR]

Reads the transcripts Claude Code keeps under ~/.claude/projects/ for the
project (default: $CLAUDE_PROJECT_DIR or the current directory).

Per session: model, steps (assistant messages), context tokens re-read, output
tokens, context size at the end, tool-result KB, check-hook blocks, check runs,
guard denials, routing tiers. --top lists the largest tool results.
"""
import argparse
import collections
import glob
import json
import os
import time

import re


def project_transcripts(project_dir):
    """Claude Code names a project's transcript folder after its path, non-alphanumerics replaced by '-'."""
    encoded = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(os.path.expanduser(project_dir)))
    return os.path.expanduser(os.path.join("~/.claude/projects", encoded))


def session(path, top):
    steps = reread = out_tokens = last_ctx = 0
    tool_kb = collections.Counter()
    biggest = []
    ids = {}
    blocks = checks = denials = 0
    tiers = collections.Counter()
    models = collections.Counter()
    title = ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            kind = e.get("type")
            m = e.get("message") or {}
            c = m.get("content")
            if kind == "assistant" and isinstance(c, list):
                steps += 1
                u = m.get("usage") or {}
                ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                reread += ctx
                last_ctx = ctx or last_ctx
                out_tokens += u.get("output_tokens", 0)
                models[(m.get("model") or "?").split("-")[1] if "-" in (m.get("model") or "") else "?"] += 1
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        ids[b["id"]] = b["name"]
                        if b["name"] == "Skill" and "check-your-work" in str(b.get("input")):
                            checks += 1
            elif kind == "user":
                if isinstance(c, str):
                    if not title and not c.startswith("<"):
                        title = c.strip().splitlines()[0][:48]
                    if "changed something since its last check" in c:
                        blocks += 1
                elif isinstance(c, list):
                    for b in c:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text":
                            t = b.get("text", "")
                            if not title and not t.startswith("<"):
                                title = t.strip().splitlines()[0][:48]
                            if "changed something since its last check" in t:
                                blocks += 1
                            if t.startswith("Routing: "):
                                tiers[t.split(".")[0][9:].split(" ")[0]] += 1
                        if b.get("type") == "tool_result":
                            s = b.get("content")
                            s = s if isinstance(s, str) else json.dumps(s)
                            n = ids.get(b.get("tool_use_id"), "?")
                            tool_kb[n] += len(s) / 1024
                            if "Read the part you need" in s or "#full" in s:
                                denials += 1
                            if top:
                                biggest.append((len(s) / 1024, n, s[:70].replace("\n", " ")))
    return {"file": os.path.basename(path)[:8], "title": title, "steps": steps, "reread_m": reread / 1e6,
            "out_k": out_tokens / 1e3, "ctx_k": last_ctx / 1e3, "tool_kb": sum(tool_kb.values()),
            "blocks": blocks, "checks": checks, "denials": denials, "tiers": tiers, "models": models,
            "biggest": sorted(biggest, reverse=True)[:8], "mtime": os.path.getmtime(path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=8)
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--top", action="store_true")
    ap.add_argument("--project", default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    a = ap.parse_args()
    folder = project_transcripts(a.project)
    files = sorted(glob.glob(os.path.join(folder, "*.jsonl")), key=os.path.getmtime)
    if not files:
        print(f"no transcripts found in {folder}")
        return
    if a.days:
        files = [f for f in files if os.path.getmtime(f) > time.time() - a.days * 86400]
    files = files[-a.last:]
    rows = [session(f, a.top) for f in files]
    print(f"{'session':8} {'date':10} {'model':7} {'steps':>5} {'reread M':>9} {'out K':>6} {'ctx K':>6} {'tool KB':>7} {'blk':>3} {'chk':>3} {'den':>3}  title")
    tot = collections.Counter()
    for r in rows:
        model = r["models"].most_common(1)[0][0] if r["models"] else "?"
        date = time.strftime("%Y-%m-%d", time.localtime(r["mtime"]))
        print(f"{r['file']:8} {date:10} {model:7} {r['steps']:5d} {r['reread_m']:9.1f} {r['out_k']:6.0f} {r['ctx_k']:6.0f} "
              f"{r['tool_kb']:7.0f} {r['blocks']:3d} {r['checks']:3d} {r['denials']:3d}  {r['title']}")
        for k in ("steps", "reread_m", "out_k", "tool_kb", "blocks", "checks", "denials"):
            tot[k] += r[k]
        if r["tiers"]:
            print(f"{'':8} routing: " + ", ".join(f"{k} {v}" for k, v in r["tiers"].most_common()))
        if a.top and r["biggest"]:
            for kb, n, head in r["biggest"][:5]:
                print(f"{'':8}   {kb:7.0f} KB {n:24} {head}")
    print(f"{'total':8} {'':10} {'':7} {tot['steps']:5d} {tot['reread_m']:9.1f} {tot['out_k']:6.0f} {'':6} {tot['tool_kb']:7.0f} "
          f"{tot['blocks']:3d} {tot['checks']:3d} {tot['denials']:3d}")
    print("\nreread M = million context tokens re-sent across all steps (the real cost); ctx K = context size at the end;"
          "\nblk = check-hook blocks, chk = check skill runs, den = output-guard denials.")


if __name__ == "__main__":
    main()
