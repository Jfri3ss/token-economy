# Account server

A Cloudflare Worker with one D1 database. It serves the landing page, device-code sign-in with an email confirmation, the daily usage upload, the dashboard, and the plan check. The plugin works without it; `DEFAULT_ENDPOINT` in `scripts/account.py` is empty until this is live.

## Routes

| Route | What it does |
|---|---|
| `GET /` | Landing page with the install line and a team-features email list (`POST /signup`). |
| `POST /v1/device/start` | CLI starts sign-in; returns a device code (kept by the CLI) and a user code (typed in the browser). |
| `GET/POST /activate` | Browser form: user code + email. Emails a one-time confirm link that names the code. Creates no account. |
| `GET /confirm?t=` | Shows the terminal's code and a button; opening the link (or a mail scanner opening it) changes nothing. |
| `POST /confirm` | Creates or finds the account, marks the email verified, links the device code if not already linked. |
| `POST /v1/device/poll` | CLI polls; once confirmed, gets its API key exactly once. |
| `GET /v1/me`, `DELETE /v1/me` | Account, plan and entitlements; delete the account and all its data (API key only). |
| `POST /v1/usage`, `GET /v1/usage` | Upload daily counts (upsert); read them back per day. |
| `POST /v1/dashboard-link`, `GET /dashboard` | One-time 10-minute link that sets a 30-day dashboard cookie. |

Sign-in starts, emails and web sign-ups are limited per IP and per address each hour (`rate_limits` table). Uploads are capped per row and at 100,000 rows per account.

## Plans

`src/plans.js` lists what each plan includes. Every account is `free`, and free includes every hosted feature built so far. To charge later: add the feature to the paid plans, gate it with `can(user, "feature")`, and set `users.plan`. The plugin's local hooks are never gated.

## Run locally

```bash
node server/dev.mjs --port 8787
```

Uses `node:sqlite` in memory (Node 22.5+) and shows confirm links on the page instead of emailing them. Point the CLI at it with `TOKEN_ECONOMY_ENDPOINT=http://127.0.0.1:8787`.

## Live

Deployed 2026-10-27 as `token-economy-accounts` at https://token-economy-accounts.friesjeremiah.workers.dev (D1 `token-economy`). Sign-in emails come from signin@getpavo.app (verified in Resend) once `RESEND_API_KEY` is set as a Worker secret; until then sign-in stops at the email step.

## Deploy (owner)

1. `npx wrangler d1 create token-economy` and paste the id into `wrangler.toml`.
2. `npx wrangler d1 execute token-economy --remote --file schema.sql`.
3. Verify a sending domain in Resend, set `MAIL_FROM` in `wrangler.toml`, then `npx wrangler secret put RESEND_API_KEY`.
4. `npx wrangler deploy`, add a custom domain if wanted, and set `DEFAULT_ENDPOINT` in `scripts/account.py` to the URL in the same plugin release.

Never set `ALLOW_UNVERIFIED` in production: it shows the confirm link to whoever typed the email.
