"""Shared config for the token-economy hooks and scripts.

Looks for `token-economy.config.json` in, in order: $TOKEN_ECONOMY_CONFIG, the
project dir ($CLAUDE_PROJECT_DIR) and its parents, the current dir and its
parents, then ~/.claude/token-economy.config.json. Missing file = defaults, so
the hooks work, quietly, in a project that has not configured them.
"""
import json
import os

DEFAULTS = {
    # Repos the check's facts script reports on: name -> path. Empty = the project dir only.
    "repos": {},
    # Gates the check runs for touched files: glob -> shell command ({file} is replaced).
    "gates": {},
    # Optional read-only command that prints production's state (deployed commit, log tail).
    "prod_command": "",
    # Extra words that make a prompt or Agent brief "hard" for the model router.
    "hard_words": [],
    # Regex fragments for paths whose edits are notes, not code (no check needed).
    "note_paths": ["\\.(md|txt|markdown|rst)$", "/docs?/", "/reports?/", "/notes?/"],
    # Longest file the output guard lets through whole.
    "max_lines": 300,
    # Model for the subagent that runs local and shipped checks.
    "check_model": "sonnet",
}
NAME = "token-economy.config.json"


def _walk_up(start):
    d = os.path.abspath(start)
    while True:
        yield os.path.join(d, NAME)
        parent = os.path.dirname(d)
        if parent == d:
            return
        d = parent


def find_config():
    env = os.environ.get("TOKEN_ECONOMY_CONFIG")
    if env:
        return env if os.path.isfile(env) else None
    starts = [p for p in (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()) if p]
    for s in starts:
        for candidate in _walk_up(s):
            if os.path.isfile(candidate):
                return candidate
    home = os.path.expanduser("~/.claude/" + NAME)
    return home if os.path.isfile(home) else None


def load():
    cfg = dict(DEFAULTS)
    path = find_config()
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
    cfg["_path"] = path
    cfg["project_dir"] = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    cfg["plugin_root"] = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return cfg
