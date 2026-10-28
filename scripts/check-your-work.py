#!/usr/bin/env python3
"""Fast facts for the check-your-work skill. Read-only.

For each checkout: branch, commit, uncommitted files, commits not on its
upstream. With --prod: whatever the configured production command prints (deployed
commit, log tail).

    python3 scripts/check-your-work.py [--prod] [--log-lines N]
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks"))
from _config import load  # noqa: E402

CFG = load()
REPOS = {k: os.path.expanduser(v) for k, v in CFG["repos"].items()} or {"project": CFG["project_dir"]}
PROD_COMMAND = CFG["prod_command"]


def run(cmd, cwd=None, timeout=30):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return out.returncode, out.stdout.strip(), out.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, "", str(e)


def git(repo, *args):
    return run(["git", "-C", repo, *args])


def repo_facts(name, path):
    print(f"== {name}: {path}")
    if not os.path.isdir(path):
        print("   missing")
        return
    _, branch, _ = git(path, "rev-parse", "--abbrev-ref", "HEAD")
    _, head, _ = git(path, "log", "-1", "--format=%h %cd %s", "--date=format:%Y-%m-%d %H:%M")
    print(f"   branch {branch}  head {head}")
    _, status, _ = git(path, "status", "--porcelain")
    lines = [l for l in status.splitlines() if l]
    print(f"   uncommitted: {len(lines)}")
    for l in lines[:25]:
        print(f"     {l}")
    if len(lines) > 25:
        print(f"     ... {len(lines) - 25} more")
    rc, ahead, _ = git(path, "log", "--oneline", "@{upstream}..HEAD")
    if rc == 0:
        n = len([l for l in ahead.splitlines() if l])
        print(f"   unpushed commits: {n}")
        for l in ahead.splitlines()[:10]:
            print(f"     {l}")
    else:
        print("   unpushed commits: no upstream")


def prod_facts(log_lines):
    print("== production")
    if not PROD_COMMAND:
        print("   no prod_command configured (token-economy.config.json)")
        return
    rc, out, err = run(["sh", "-c", PROD_COMMAND], timeout=40)
    if rc != 0:
        print(f"   prod command failed: {err or out}")
        return
    lines = out.splitlines()
    for l in lines[:log_lines + 10]:
        print(f"   {l}")
    if len(lines) > log_lines + 10:
        print(f"   ... {len(lines) - log_lines - 10} more lines")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", action="store_true", help="also read production over SSH")
    ap.add_argument("--log-lines", type=int, default=15)
    ap.add_argument("--repos", default="", help="comma-separated repo names to report (default: all)")
    args = ap.parse_args()
    wanted = {r for r in args.repos.split(",") if r} & set(REPOS)
    for name, path in REPOS.items():
        if not wanted or name in wanted:
            repo_facts(name, path)
    if args.prod:
        prod_facts(args.log_lines)


if __name__ == "__main__":
    main()
