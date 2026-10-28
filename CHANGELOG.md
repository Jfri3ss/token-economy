# Changelog

## 0.2.3 (2026-10-28)

Fewer extra round trips. Guard: a bare `git log` or listing that is one read-only command on relative paths is now rewritten (`-n 20`, `| head -50`, with a note saying so) instead of refused; anything with an absolute, home or parent path, chaining or substitution is still refused, and test and build runs are always refused, because a rewrite must be approved by the hook and those run code. Router: plain "token", "session", "table", "index", "release" and "terms" no longer make a prompt hard (only pairings like "access token" or "database table" do); a question is hard only when it asks why something fails or names one of your `hard_words`; "do 1–4", "do all of them" route as go-aheads; and on a session's first prompt the model is read from `ANTHROPIC_MODEL` or settings, and an unknown model no longer sends the work to a top-model Agent. Check: a `**Check: not needed**` line ends the request, so the same changes stop blocking every later turn; the facts list only the repos the changes touch. Ledger: `chk` counts check subagents as well as skill runs.

## 0.2.2 (2026-10-28)

Ledger `--rules`: denials, overrides, the cost of the extra round trip and an estimate of what the smaller retries saved, per guard rule, with a verdict that marks rules to loosen or drop. The guard now ends each denial with `[guard rule: <id>]`; older denials are matched by their wording. Fixed: when the denied call was one of several in a step, its sibling calls were taken for the retry, so some overrides were missed.

## 0.2.1 (2026-10-27)

Accounts are on: `scripts/account.py login` signs in against the live account server, and sign-in emails come from signin@getpavo.app. Uploads stay off until you turn them on.

## 0.2.0 (2026-10-27)

Ledger: each model step is now counted once (Claude Code writes one step as several transcript lines with the same usage, so 0.1.x counted steps and tokens about 2–3 times over); guard denials are read from the hook's own error shape, a new `ovr` column counts denials rerun as written with `#full` or `allow_large` (a likely false positive), and `--compare YYYY-MM-DD` prints step-weighted rates before and after a date. Optional free account: `scripts/account.py` (device-code sign-in, opt-in daily upload of counts only, dashboard, delete), a SessionStart hook that syncs at most once a day in the background, and the account server in `server/` (Cloudflare Worker + D1, plan check with every account on free). The account server is deployed (token-economy-accounts on Cloudflare); accounts stay off in the plugin until sign-in email is set up and `DEFAULT_ENDPOINT` is set. The end-of-turn check now counts a check run in a subagent (its launch with the check brief, or its report coming back), so it no longer asks for the same check again and again.

## 0.1.1 (2026-10-26)

Social preview image, icon and directory listing fields; privacy note; README quick start with examples of what you'll see; short go-aheads like "do it" route as continuations.

## 0.1.0 (2026-10-26)

First release: model router (UserPromptSubmit and Agent guard), output guard (Read and Bash), sized end-of-turn check (Stop and PostToolUse) with the check-your-work skill, facts script, token ledger, config file, tests.
