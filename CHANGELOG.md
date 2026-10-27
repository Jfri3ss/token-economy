# Changelog

## 0.2.0 (unreleased)

Ledger: each model step is now counted once (Claude Code writes one step as several transcript lines with the same usage, so 0.1.x counted steps and tokens about 2–3 times over); guard denials are read from the hook's own error shape, a new `ovr` column counts denials rerun as written with `#full` or `allow_large` (a likely false positive), and `--compare YYYY-MM-DD` prints step-weighted rates before and after a date. Optional free account: `scripts/account.py` (device-code sign-in, opt-in daily upload of counts only, dashboard, delete), a SessionStart hook that syncs at most once a day in the background, and the account server in `server/` (Cloudflare Worker + D1, plan check with every account on free). Accounts stay off until the server is deployed and `DEFAULT_ENDPOINT` is set.

## 0.1.1 (2026-10-26)

Social preview image, icon and directory listing fields; privacy note; README quick start with examples of what you'll see; short go-aheads like "do it" route as continuations.

## 0.1.0 (2026-10-26)

First release: model router (UserPromptSubmit and Agent guard), output guard (Read and Bash), sized end-of-turn check (Stop and PostToolUse) with the check-your-work skill, facts script, token ledger, config file, tests.
