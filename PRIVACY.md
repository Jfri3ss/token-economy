# Privacy

token-economy runs entirely on your machine. It collects nothing, sends nothing and has no server.

- The hooks read the hook event Claude Code passes them and, for the end-of-turn check, the session transcript Claude Code already keeps on your disk. They print a short instruction back to Claude Code and keep no state.
- The ledger reads the same local transcripts and prints a table to your terminal.
- The only commands that reach the network are ones you configure yourself: `git fetch` in the check's facts script, and your own `prod_command` in `token-economy.config.json`.

Questions: open an issue at https://github.com/Jfri3ss/token-economy/issues.
