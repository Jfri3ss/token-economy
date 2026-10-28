# Model routing

Where each kind of work runs, so the top model spends its limit on judgment and the cheap models do the reading, testing and typing. A session cannot change its own model (the app refuses it), so the switch happens per task: the session keeps its model and hands the heavy part to an Agent or side session on the right one. `hooks/model-router-hook.py` classifies every prompt and adds one routing line; its Agent guard refuses Agent calls whose model does not fit the brief.

## The matrix

| Task | Signal in the prompt | Top-model session does | Sonnet session does | Agent model |
|---|---|---|---|---|
| Question | starts with what/why/how/is/can…, no action verb | answers from context, one grep at most | same | none |
| Read-only | find, where, list, search, summarize, review, audit, how many | delegates and relays | delegates and relays | haiku (sonnet to weigh evidence) |
| Routine edit | fix/update + typo, wording, doc, comment, bump, label, .md | one sonnet Agent edits; main checks the diff by path | edits directly | sonnet |
| Build | add, implement, create, refactor (no hard signal) | designs and edits here; wide reads and suites go out | edits here; wide reads go out | haiku for reads |
| Hard | auth, security, schema, migration, deploy, production, design, refactor, debug, crash, failing, legal, plus your `hard_words` (a question counts only when it asks why something fails, or names one of your `hard_words`) | does it here; reads and tests go out | runs the design or diagnosis in one top-model Agent, implements here | top model for the thinking, sonnet/haiku for the rest |

Checks: the end-of-turn check runs in an Agent on `check_model` (default sonnet) for local and shipped changes, in the main session for deploys (`hooks/check-your-work-hook.py`).

## Choosing the session model

- Daily development sessions: pick **Sonnet** in the model menu. The router escalates the hard step to a top-model Agent when the task calls for it, and that costs a fraction of running the whole session on the top model.
- Design, architecture and incident sessions: pick the top model. The router then pushes everything mechanical out to cheap Agents.
- Side sessions started from a top-model session may be set to a cheaper model without a prompt (`set_session_model`); escalating a side session asks you once.

## Why it is safe

The cheap models never decide anything the matrix calls hard: the Agent guard refuses a haiku Agent whose brief mentions design, diagnosis, payments, auth, schema or deploy. The deterministic gates (tests, lint, type check, endpoint check) run the same whichever model triggers them. A wrong tier costs at most one wasted step; a `#full`-style override is the prompt itself: say "do this here" and the routing line is ignored.

## Tuning

Tier rules are regexes at the top of `hooks/model-router-hook.py`; add domain words through `hard_words` in `token-economy.config.json`; tests in `tests/test_model_router.py`. The ledger (`scripts/token-ledger.py`) shows per-session steps and the share on each model, so a change to the matrix can be measured a week later.
