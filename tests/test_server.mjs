// Tests for the account server. Run: node tests/test_server.mjs
import worker from "../server/src/worker.js";
import { fakeD1 } from "../server/dev.mjs";
import { PLANS } from "../server/src/plans.js";

let passed = 0, failed = 0;
const check = (name, ok) => { if (ok) passed++; else { failed++; console.log("FAIL", name); } };

const env = { DB: fakeD1(), ALLOW_UNVERIFIED: "1" };
const call = (method, path, body, headers = {}) => worker.fetch(new Request(`http://local${path}`, {
  method, headers: { "content-type": body instanceof URLSearchParams ? "application/x-www-form-urlencoded" : "application/json", ...headers },
  body: body === undefined ? undefined : body instanceof URLSearchParams ? body : JSON.stringify(body),
}), env);

async function signIn(email) {
  const start = await (await call("POST", "/v1/device/start", {})).json();
  check("pending before confirm", (await call("POST", "/v1/device/poll", { device_code: start.device_code })).status === 202);
  const page = await (await call("POST", "/activate", new URLSearchParams({ user_code: start.user_code.toLowerCase(), email }))).text();
  const link = page.match(/href="http:\/\/local(\/confirm\?t=[a-f0-9]+)"/);
  check("confirm link shown in test mode", Boolean(link));
  const shown = await call("GET", link[1]);
  const shownText = await shown.text();
  check("confirm page shows the terminal's code", shown.status === 200 && shownText.includes(start.user_code));
  check("opening the link (mail scanner) signs nothing in", (await call("POST", "/v1/device/poll", { device_code: start.device_code })).status === 202);
  const t = link[1].split("?t=")[1];
  check("confirm ok", (await call("POST", "/confirm", new URLSearchParams({ t }))).status === 200);
  check("confirm token single use", (await call("POST", "/confirm", new URLSearchParams({ t }))).status === 410);
  check("confirmed code takes no more emails", (await call("POST", "/activate", new URLSearchParams({ user_code: start.user_code, email: "evil@example.com" }))).status === 400);
  const polls = await Promise.all([1, 2].map(() => call("POST", "/v1/device/poll", { device_code: start.device_code })));
  const keys = (await Promise.all(polls.map((r) => r.json()))).filter((j) => j.api_key);
  check("exactly one poll gets a key", keys.length === 1);
  return keys[0].api_key;
}

const key = await signIn("Dev@Example.com");
const auth = { authorization: `Bearer ${key}` };
const me = await (await call("GET", "/v1/me", undefined, auth)).json();
check("email lowercased", me.email === "dev@example.com");
check("plan free with dashboard", me.plan === "free" && me.entitlements.dashboard === true && me.entitlements.team === false);
check("no key -> 401", (await call("GET", "/v1/me")).status === 401);
check("bad key -> 401", (await call("GET", "/v1/me", undefined, { authorization: "Bearer te_" + "0".repeat(40) })).status === 401);
check("key not stored in plain text", !JSON.stringify(env.DB.raw.prepare("SELECT * FROM api_keys").all()).includes(key));

const device_id = "a".repeat(32);
const row = { day: new Date(Date.now() - 5 * 86400000).toISOString().slice(0, 10), project: "b".repeat(16), sessions: 2, steps: 100, reread: 3e7, out_tokens: 5000, tool_bytes: 9000, blocks: 1, checks: 1, denials: 4, overrides: 1 };
check("upload ok", (await call("POST", "/v1/usage", { device_id, rows: [row], version: "0.2.0" }, auth)).status === 200);
check("re-upload replaces, not adds", (await call("POST", "/v1/usage", { device_id, rows: [{ ...row, steps: 120 }] }, auth)).status === 200);
const usage = await (await call("GET", "/v1/usage?days=3650", undefined, auth)).json();
check("usage read back", usage.days.length === 1 && usage.days[0].steps === 120 && usage.days[0].overrides === 1);
check("bad row rejected", (await call("POST", "/v1/usage", { device_id, rows: [{ ...row, project: "../etc" }] }, auth)).status === 400);
check("huge count rejected", (await call("POST", "/v1/usage", { device_id, rows: [{ ...row, reread: 1e13 }] }, auth)).status === 400);
check("ancient day rejected", (await call("POST", "/v1/usage", { device_id, rows: [{ ...row, day: "2001-01-01" }] }, auth)).status === 400);
check("negative count rejected", (await call("POST", "/v1/usage", { device_id, rows: [{ ...row, steps: -1 }] }, auth)).status === 400);
check("bad device rejected", (await call("POST", "/v1/usage", { device_id: "x", rows: [] }, auth)).status === 400);

const other = await signIn("other@example.com");
const theirs = await (await call("GET", "/v1/usage?days=3650", undefined, { authorization: `Bearer ${other}` })).json();
check("users don't see each other's numbers", theirs.days.length === 0);

const link = await (await call("POST", "/v1/dashboard-link", {}, auth)).json();
const t = link.url.split("?t=")[1];
const redirect = await call("GET", `/dashboard?t=${t}`);
const cookie = (redirect.headers.get("set-cookie") || "").split(";")[0];
check("dashboard link sets a secure cookie", redirect.status === 303 && /HttpOnly; Secure; SameSite=Lax/.test(redirect.headers.get("set-cookie")));
check("dashboard link single use", (await call("GET", `/dashboard?t=${t}`)).status === 410);
const dash = await call("GET", "/dashboard", undefined, { cookie });
const nonce = (dash.headers.get("content-security-policy").match(/'nonce-([a-f0-9]+)'/) || [])[1];
check("dashboard with cookie", dash.status === 200);
check("dashboard script runs only by nonce", nonce && (await dash.text()).includes(`<script nonce="${nonce}">`));
check("other pages allow no script", /script-src 'none'/.test((await call("GET", "/")).headers.get("content-security-policy")));
check("usage with cookie", (await call("GET", "/v1/usage", undefined, { cookie })).status === 200);
check("dashboard without cookie", (await call("GET", "/dashboard")).status === 401);
check("cookie can't delete the account", (await call("DELETE", "/v1/me", undefined, { cookie })).status === 401);

env.DB.raw.prepare("UPDATE users SET plan = 'nonexistent' WHERE email = 'other@example.com'").run();
check("unknown plan falls back to free", (await (await call("GET", "/v1/me", undefined, { authorization: `Bearer ${other}` })).json()).entitlements.dashboard === true);
PLANS.free.cloud_ledger = false;
check("plan check gates uploads", (await call("POST", "/v1/usage", { device_id, rows: [] }, auth)).status === 403);
PLANS.free.cloud_ledger = true;

const xss = await (await call("POST", "/activate", new URLSearchParams({ user_code: "x", email: '"><script>alert(1)</script>' }))).text();
check("email escaped on error page", !xss.includes("<script>alert"));
check("web signup", (await call("POST", "/signup", new URLSearchParams({ email: "lead@example.com" }))).status === 200);
check("typing an email on /activate creates no account", !env.DB.raw.prepare("SELECT 1 FROM users WHERE email = 'x@example.com'").get());
check("comma in email rejected", (await call("POST", "/signup", new URLSearchParams({ email: "a@b.com,c@d.com" }))).status === 400);
check("web signup bad email", (await call("POST", "/signup", new URLSearchParams({ email: "nope" }))).status === 400);
const noMail = await worker.fetch(new Request("http://local/v1/device/start", { method: "POST" }), { DB: env.DB });
const code = (await noMail.json()).user_code;
const sent = await worker.fetch(new Request("http://local/activate", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
  body: new URLSearchParams({ user_code: code, email: "x@example.com" }) }), { DB: env.DB });
check("without test mode or mail keys, no link is shown", sent.status === 502 && !(await sent.text()).includes("/confirm?t="));

check("delete account", (await call("DELETE", "/v1/me", undefined, auth)).status === 200);
check("upload after delete leaves no rows", (await call("POST", "/v1/usage", { device_id, rows: [row] }, auth)).status === 401 &&
  env.DB.raw.prepare("SELECT COUNT(*) AS n FROM usage").get().n === 0);
let limitedHit = false;
for (let i = 0; i < 40 && !limitedHit; i++) limitedHit = (await call("POST", "/v1/device/start", {})).status === 429;
check("sign-in starts are rate limited", limitedHit);
check("key dead after delete", (await call("GET", "/v1/me", undefined, auth)).status === 401);
check("usage gone after delete", env.DB.raw.prepare("SELECT COUNT(*) AS n FROM usage").get().n === 0);

console.log(`passed: ${passed}, failed: ${failed}`);
