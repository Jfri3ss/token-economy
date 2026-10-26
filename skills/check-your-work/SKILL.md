---
name: check-your-work
description: >-
  The end-of-turn "check your work" pass over whatever this session just
  changed: code, config, docs, settings, a deploy or a migration. Lists what
  changed, confirms it does what was asked, re-reads the diff, runs the gates
  for what was touched, sees it working, runs the post-deploy checks if
  something shipped, confirms the records were updated, then reports in a fixed
  shape. The token-economy Stop hook asks for it automatically, sized to the
  change. Use also when the user says "check your work", "did that work" or
  "verify that change".
---

# Check your work

One pass over **this session's own changes since the last check**, sized to the change. A one-line doc fix gets a three-line check; a deploy gets every section.

The hook sizes it (`hooks/check-your-work-hook.py`): note-only changes get no check; local and shipped changes run sections 1, 3 and 4 (plus 7 and 8 when something was committed or pushed) in a subagent on the configured `check_model`, which receives the change list and the facts script's output; deploys and anything that touched a remote system run every section in the main session. Read diffs by path and pipe test output through `tail`, so the check itself stays small.

The facts script prints each configured repo's branch, uncommitted and unpushed files, and (with `--prod`) whatever the configured production command prints. It only reads:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/check-your-work.py" --prod
```

Leave out `--prod` when nothing touched a remote system. Repos, gates and the production command come from `token-economy.config.json` (see `config.example.json`).

## 1. What changed

From this conversation and git, list every change since the last check: files (by repo and path), commits, pushes, PRs opened or merged, deploys, migrations, env or settings edits, messages sent, files deleted. Include changes made by subagents. If you cannot account for a change the script shows, say whose it probably is and leave it alone: other sessions may work in the same folders.

## 2. Does it do what was asked

Re-read the user's actual words. For each thing they asked for, say done, partly done or not done. Name anything you added that they did not ask for, and anything you skipped.

## 3. Re-read the diff

Read the real diff (`git diff -- path`, `git show --stat`, or the file by range), not your memory of it. Look for: bugs and edge cases, leftover debug output, hard-coded test values, secrets or customer data, files changed by accident, other sessions' files swept into a commit, and comments or copy that now say something untrue.

## 4. Run the gates for what was touched

Run only what applies, and record exact results (counts, not "passed"):

- The configured gate for each touched file type (`gates` in the config): lint, unit tests for the touched area, type check.
- The full suite before any merge or deploy.
- Config, JSON, YAML, env, crontab: parse or lint it, and read it back from where it was written.
- Scripts: run once on real input.

Keep output short: `2>&1 | tail -40`, or grep for the failure lines.

## 5. See it working

Prove the change from the outside where you can: open the page, call the endpoint, run the command, read the setting back. Say plainly when this was not possible and why.

## 6. If something was deployed or run on production

Every time: the deployed commit equals the one you meant to ship and nothing else is in the range; the live assets match; the application log since the deploy, and what each new line is; scheduled jobs against the copy taken before; each migration's output, and a second run being a no-op; health on every host. Then write the deploy record wherever the project keeps it.

## 7. Side effects and safety

- Installed clients still work: no response field they read was renamed or removed, no path they call now fails.
- Nothing was committed to a branch that belongs to other work; no branch was switched, stashed, reset or cleaned.
- Nothing destructive happened that the user did not approve.
- No secret was printed into chat, a commit, a PR or a report.

## 8. Records

Update what the change made untrue, in the same piece of work: docs, changelogs, to-do lists, memory files. Check that what they now say matches git and the remote (PR states, commits, switch defaults).

## 9. Report

If the check found a problem you can fix safely within what the user asked, fix it and run the affected parts again. Anything that needs the user, or is outside the request, goes in the report instead.

Reply in this shape, short, with no section that has nothing in it:

**Check: clean** (or **Check: found problems**)

- **Changed:** one line per change.
- **Verified:** each gate or proof with its exact result.
- **Found and fixed:** what was wrong and the fix.
- **Not checked:** what could not be checked, and why.
- **Needs you:** decisions or steps only the user can take.

Be exact. If a test failed, show the output. If something was not run, say so. Do not call a change verified that was only read.
