# Privacy

token-economy runs on your machine. Without an account it collects nothing and sends nothing.

## Without an account (the default)

- The hooks read the hook event Claude Code passes them and, for the end-of-turn check, the session transcript Claude Code already keeps on your disk. They print a short instruction back to Claude Code and keep no state.
- The ledger reads the same local transcripts and prints a table to your terminal.
- The only commands that reach the network are ones you configure yourself: `git fetch` in the check's facts script, and your own `prod_command` in `token-economy.config.json`.

## With the optional free account

Nothing changes until you run `scripts/account.py login`. Signing in stores your email and a random API key on our server. The key is stored only as a hash; your copy lives in `~/.claude/token-economy/account.json`, readable only by you.

**Uploads are off until you turn them on** (`login --upload` or `account.py upload on`). When on, once a day at session start the plugin sends, per day and per project:

- counts: sessions, model steps, context tokens re-read, output tokens, tool-output bytes, check-hook blocks, check runs, output-guard denials and overrides;
- the plugin version and a random ID for the machine;
- the project as a 16-character hash salted with a random value kept on your machine, so we can't tell which project it is.

**Never sent:** prompts, replies, session titles, code, file names or paths, tool output, or anything from your transcripts besides those counts. `tests/test_account.py` checks this.

We use the numbers to show you your dashboard. We don't sell them or share them. Later we may add paid team features built on the same numbers; anything that changes what is collected will be opt-in.

**Delete everything:** `python3 scripts/account.py logout --delete` erases your account, keys and every uploaded number. `upload off` stops uploads and keeps the account.

The account server is run by Emmber, Inc. on Cloudflare (Workers and D1). Sign-in emails are sent through Resend.

Questions: open an issue at https://github.com/Jfri3ss/token-economy/issues.
