# token-economy

Hooks for Claude Code that cut token spend without lowering the bar on the work. Four pieces:

- **Model router.** Classifies every prompt and tells the session where the heavy part should run, so a top model spends its limit on judgment and cheaper models do the reading, testing and typing. Refuses an Agent call whose model does not fit its brief.
- **Output guard.** Refuses the few command shapes that dump thousands of lines into the context (whole-file reads, bare `git diff`, untailed test runs, long listings) and names the smaller form.
- **Sized end-of-turn check.** A Stop hook that asks the session to check its own changes, sized to what changed: nothing for a doc edit, a subagent check for code, the full check for a deploy.
- **Ledger.** A script that reads the session transcripts and shows where the tokens went.

## Why

Measured over a week of real sessions on one project, the cost was not tool output. It was model steps multiplied by context size: every step re-sends the whole conversation, so a session that grows to 800K tokens of context pays that on every one of its steps. One session of 944 steps re-read 435 million tokens; the six sessions around it, 145 million together. Tool output over the same week was 2.5 MB, about 600K tokens. A check hook that fired at the end of every turn, when the context was largest, blocked 61 times for 16 real checks.

So the levers are, in order: fewer and shorter sessions, fewer steps per turn, a smaller fixed context, and keeping the work that does not need the top model off it. These hooks handle the parts that can be automated.

## Install

With a marketplace (needed for install by name and for updates):

```bash
claude plugin marketplace add Jfri3ss/token-economy
claude plugin install token-economy@emmber
```

Or clone it and run `claude --plugin-dir ./token-economy`.

Without the plugin system, copy `hooks/` and `scripts/` somewhere and register the five hook commands from `hooks/hooks.json` in your `.claude/settings.json`, replacing `${CLAUDE_PLUGIN_ROOT}` with the folder.

Python 3.9 or later. No dependencies.

## Configure

Optional. Without a config the hooks use defaults and the check's facts script reports on the project directory only. Copy `config.example.json` to `token-economy.config.json` in your project (or `~/.claude/token-economy.config.json`) and fill in:

| Key | What it does |
|---|---|
| `repos` | Name to path. The check's facts script reports each one's branch, uncommitted and unpushed files. |
| `gates` | File glob to shell command. The check runs the matching gate for each touched file (`{file}` is replaced). |
| `prod_command` | Read-only shell command that prints production's state. Run only for the deploy tier. |
| `hard_words` | Your domain's words that make a task "hard" (payments, billing, whatever must not go to a cheap model). |
| `note_paths` | Regex fragments for paths whose edits are notes, not code. No check for those. |
| `max_lines` | Longest file the guard lets through whole. Default 300. |
| `check_model` | Model for the subagent that runs local and shipped checks. Default `sonnet`. |

## How the router works

A session cannot change its own model (Claude Code refuses it), but the Agent tool takes a model and so do side sessions. So the switch is per task. The hook adds one line of context per prompt:

| Tier | Signal | On a top-model session | On a Sonnet session |
|---|---|---|---|
| question | starts with what, why, how, is, can…; no action verb | answer, one grep at most | same |
| read | find, where, list, search, summarize, review, audit | delegate to a haiku Agent, relay | same |
| routine | fix/update plus typo, wording, doc, comment, bump | one sonnet Agent edits, main checks the diff | edit directly |
| build | add, implement, create, refactor | design and delicate edits here, wide reads out | edit here, reads out |
| hard | auth, security, schema, migration, deploy, design, crash, failing, plus `hard_words` | do it here, reads and tests out | one top-model Agent for the diagnosis or design, implement here |

The saving depends on picking a cheaper session model for everyday work and letting the router escalate the hard step. Full matrix in [MODEL-ROUTING.md](MODEL-ROUTING.md).

## The guard's rules and the override

Read of a file over `max_lines` with no range; `cat` of such a file with no pipe; `git diff` or `git show` with no path, ref or `--stat`; `git log` with no count, range or `--since`; test, lint, type-check and build runs with no `| tail`, `| grep` or redirect; `find`, `ls -R` and `tree` with no `| head` (shallow or `-exec` finds pass). Each denial names the smaller form. Put `#full` anywhere in a command to run it as written; pass `allow_large` to Read.

## The check

`skills/check-your-work/SKILL.md` is a nine-section pass: what changed, does it do what was asked, re-read the diff, run the gates, see it working, post-deploy checks, side effects, records, report. The Stop hook decides the tier from the transcript:

| Tier | Trigger | What happens |
|---|---|---|
| note | only note paths changed | nothing |
| local | files edited, nothing committed | sections 1, 3, 4 in a `check_model` subagent |
| shipped | commit, push, PR, merge | sections 1, 3, 4, 7, 8 in a subagent |
| deploy | deploy script, ssh, mysql, crontab, console writes | the full check in the main session |

The brief carries the change list and the facts script's output, so no steps go to re-deriving them. A `**Check: clean**` or `**Check: found problems**` line in the reply counts as a check, so the hook does not block twice. Say "skip the check" in a prompt to skip it once.

## The ledger

```bash
python3 scripts/token-ledger.py --last 8          # this project
python3 scripts/token-ledger.py --project ~/other  # another project
python3 scripts/token-ledger.py --top              # the largest tool results
```

Columns: steps, million context tokens re-read across all steps (the real cost), output tokens, context size at the end, tool-result KB, check-hook blocks, check runs, guard denials, routing tiers.

## Caveats

- The hooks are regexes. They will have false positives in a codebase that uses words differently; `#full` and the tests are the escape hatches, and a report of a false positive with the command is welcome.
- A session's own model stays what you picked. The router moves work, it does not re-price the session.
- The subagent check knows only what the brief tells it. Deploys and anything over a remote connection stay in the main session for that reason.
- The ledger reads Claude Code's transcript files, whose shape is not a documented contract.

## Tests

```bash
sh tests/run.sh
```

## License

MIT. Copyright 2026 Emmber, Inc.
