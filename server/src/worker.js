// token-economy account server: a Cloudflare Worker with one D1 database (binding DB).
//
// Env: DB (D1), RESEND_API_KEY and MAIL_FROM (confirmation emails), ALLOW_UNVERIFIED="1"
// (local tests only: show the confirm link on the page instead of emailing it).
import { can, entitlements } from "./plans.js";
import { page, landing, activateForm, confirmPage, message, dashboard } from "./pages.js";

const DEVICE_TTL = 600;
const CONFIRM_TTL = 1800;
const LINK_TTL = 600;
const SESSION_TTL = 30 * 86400;
const CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ";
const COUNTS = ["sessions", "steps", "reread", "out_tokens", "tool_bytes", "blocks", "checks", "denials", "overrides"];
const EMAIL = /^[^\s@<>"',;]{1,64}@[^\s@<>"',;]{1,190}\.[a-z]{2,24}$/i;
const MAX_COUNT = 1e12;
const MAX_ROWS_PER_USER = 100000;

const now = () => Math.floor(Date.now() / 1000);

function randomHex(bytes) {
  const b = crypto.getRandomValues(new Uint8Array(bytes));
  return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
}

function userCode() {
  const b = crypto.getRandomValues(new Uint8Array(8));
  const s = [...b].map((x) => CODE_ALPHABET[x % CODE_ALPHABET.length]).join("");
  return `${s.slice(0, 4)}-${s.slice(4)}`;
}

async function sha256(s) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
const html = (body, status = 200, headers = {}, nonce = null) =>
  new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "content-security-policy": `default-src 'none'; style-src 'unsafe-inline'; script-src ${nonce ? `'nonce-${nonce}'` : "'none'"}; connect-src 'self'; form-action 'self'; frame-ancestors 'none'`,
      "referrer-policy": "no-referrer",
      ...headers,
    },
  });

async function body(request) {
  const type = request.headers.get("content-type") || "";
  try {
    if (type.includes("application/json")) return (await request.json()) || {};
    if (type.includes("form")) return Object.fromEntries(await request.formData());
  } catch {
    return {};
  }
  return {};
}

async function userFromKey(env, request) {
  const auth = request.headers.get("authorization") || "";
  const m = auth.match(/^Bearer\s+(te_[a-f0-9]{40})$/);
  if (!m) return null;
  const hash = await sha256(m[1]);
  const user = await env.DB.prepare(
    "SELECT users.* FROM api_keys JOIN users ON users.id = api_keys.user_id WHERE api_keys.key_hash = ?"
  ).bind(hash).first();
  if (user) await env.DB.prepare("UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?").bind(now(), hash).run();
  return user;
}

function cookie(request, name) {
  const m = (request.headers.get("cookie") || "").match(new RegExp(`(?:^|;\\s*)${name}=([a-f0-9]{64})`));
  return m ? m[1] : null;
}

async function takeToken(env, raw, kind, consume = true) {
  if (!raw || !/^[a-f0-9]{64}$/.test(raw)) return null;
  const hash = await sha256(raw);
  // Consuming deletes and returns in one statement, so two requests can't both use a one-time token.
  const verb = consume ? "DELETE FROM tokens" : "SELECT * FROM tokens";
  return env.DB.prepare(`${verb} WHERE token_hash = ? AND kind = ? AND expires_at > ?${consume ? " RETURNING *" : ""}`)
    .bind(hash, kind, now()).first();
}

async function newToken(env, kind, userId, ttl, ref = null, email = null) {
  const raw = randomHex(32);
  await env.DB.prepare("INSERT INTO tokens (token_hash, kind, user_id, ref, email, expires_at) VALUES (?, ?, ?, ?, ?, ?)")
    .bind(await sha256(raw), kind, userId, ref, email, now() + ttl).run();
  return raw;
}

// True once key has been hit more than max times in the current hour.
async function limited(env, key, max) {
  const win = Math.floor(now() / 3600);
  const row = await env.DB.prepare(
    `INSERT INTO rate_limits (key, win, count) VALUES (?, ?, 1)
     ON CONFLICT(key) DO UPDATE SET count = CASE WHEN win = excluded.win THEN count + 1 ELSE 1 END, win = excluded.win
     RETURNING count`
  ).bind(key, win).first();
  return row.count > max;
}

const clientIp = (request) => request.headers.get("cf-connecting-ip") || "local";

async function userFromSession(env, request) {
  const row = await takeToken(env, cookie(request, "te_session"), "session", false);
  return row ? env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(row.user_id).first() : null;
}

async function findOrCreateUser(env, email, source) {
  email = email.trim().toLowerCase();
  await env.DB.prepare("INSERT OR IGNORE INTO users (email, source, created_at) VALUES (?, ?, ?)").bind(email, source, now()).run();
  return env.DB.prepare("SELECT * FROM users WHERE email = ?").bind(email).first();
}

async function sendConfirm(env, email, link, code) {
  if (!env.RESEND_API_KEY || !env.MAIL_FROM) return false;
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({
      from: env.MAIL_FROM,
      to: [email],
      subject: "Confirm your token-economy sign-in",
      text: `Hello,\n\nSomeone asked to sign in to token-economy as you from a terminal showing the code ${code}.\n\n` +
        `If that's you and your terminal shows ${code}, open this link and confirm:\n\n${link}\n\n` +
        `It works once and expires in 30 minutes. If you didn't start a sign-in, ignore this email and nothing happens.\n\ntoken-economy by Emmber, Inc.`,
    }),
  });
  return r.ok;
}

// ---- API ----

async function deviceStart(env, request, origin) {
  if (await limited(env, `start:${clientIp(request)}`, 30)) return json({ error: "too many sign-ins, try again later" }, 429);
  const device = randomHex(32);
  let code;
  for (let i = 0; i < 5; i++) {
    code = userCode();
    const taken = await env.DB.prepare("SELECT 1 FROM device_codes WHERE user_code = ?").bind(code).first();
    if (!taken) break;
  }
  await env.DB.prepare("DELETE FROM device_codes WHERE expires_at < ?").bind(now()).run();
  await env.DB.prepare("DELETE FROM tokens WHERE expires_at < ?").bind(now()).run();
  await env.DB.prepare("DELETE FROM rate_limits WHERE win < ?").bind(Math.floor(now() / 3600) - 1).run();
  await env.DB.prepare("INSERT INTO device_codes (device_code_hash, user_code, expires_at) VALUES (?, ?, ?)")
    .bind(await sha256(device), code, now() + DEVICE_TTL).run();
  return json({ device_code: device, user_code: code, verify_url: `${origin}/activate`, interval: 3, expires_in: DEVICE_TTL });
}

async function devicePoll(env, data) {
  if (!/^[a-f0-9]{64}$/.test(data.device_code || "")) return json({ error: "bad device_code" }, 400);
  const hash = await sha256(data.device_code);
  const row = await env.DB.prepare("SELECT * FROM device_codes WHERE device_code_hash = ? AND expires_at > ?").bind(hash, now()).first();
  if (!row) return json({ error: "expired" }, 410);
  if (!row.user_id) return json({ status: "pending" }, 202);
  // Claim the row first so two polls can't both get a key.
  const del = await env.DB.prepare("DELETE FROM device_codes WHERE device_code_hash = ? AND user_id IS NOT NULL").bind(hash).run();
  if (!del.meta || !del.meta.changes) return json({ error: "expired" }, 410);
  const key = `te_${randomHex(20)}`;
  await env.DB.prepare("INSERT INTO api_keys (key_hash, user_id, created_at) VALUES (?, ?, ?)").bind(await sha256(key), row.user_id, now()).run();
  const user = await env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(row.user_id).first();
  return json({ api_key: key, email: user.email, plan: user.plan });
}

function cleanRow(r) {
  if (!r || typeof r !== "object") return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(r.day || "") || !/^[a-f0-9]{16}$/.test(r.project || "")) return null;
  const oldest = new Date(Date.now() - 400 * 86400000).toISOString().slice(0, 10);
  const newest = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  if (r.day < oldest || r.day > newest) return null;
  const out = { day: r.day, project: r.project };
  for (const k of COUNTS) {
    const v = Number(r[k] ?? 0);
    if (!Number.isSafeInteger(v) || v < 0 || v > MAX_COUNT) return null;
    out[k] = v;
  }
  return out;
}

async function usageUpload(env, user, data) {
  if (!can(user, "cloud_ledger")) return json({ error: "not on this plan" }, 403);
  if (!/^[a-f0-9]{32}$/.test(data.device_id || "")) return json({ error: "bad device_id" }, 400);
  const rows = Array.isArray(data.rows) ? data.rows : [];
  if (rows.length > 5000) return json({ error: "too many rows" }, 413);
  const clean = rows.map(cleanRow);
  if (clean.some((r) => !r)) return json({ error: "bad row" }, 400);
  const have = await env.DB.prepare("SELECT COUNT(*) AS n FROM usage WHERE user_id = ?").bind(user.id).first();
  // Re-uploads overwrite rows, so only refuse once the account is already full.
  if (have.n >= MAX_ROWS_PER_USER) return json({ error: "storage limit reached" }, 413);
  const version = String(data.version || "").slice(0, 20);
  const sql = `INSERT INTO usage (user_id, device_id, day, project, ${COUNTS.join(", ")}, version, updated_at)
    SELECT ?, ?, ?, ?, ${COUNTS.map(() => "?").join(", ")}, ?, ? WHERE EXISTS (SELECT 1 FROM api_keys WHERE user_id = ?)
    ON CONFLICT(user_id, device_id, day, project) DO UPDATE SET ${COUNTS.map((k) => `${k} = excluded.${k}`).join(", ")},
    version = excluded.version, updated_at = excluded.updated_at`;
  const stmts = clean.map((r) => env.DB.prepare(sql).bind(user.id, data.device_id, r.day, r.project, ...COUNTS.map((k) => r[k]), version, now(), user.id));
  for (let i = 0; i < stmts.length; i += 100) await env.DB.batch(stmts.slice(i, i + 100));
  return json({ stored: clean.length });
}

async function usageRead(env, user, url) {
  if (!can(user, "dashboard")) return json({ error: "not on this plan" }, 403);
  const days = Math.min(Math.max(parseInt(url.searchParams.get("days") || "90", 10) || 90, 1), 365);
  const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
  const { results } = await env.DB.prepare(
    `SELECT day, ${COUNTS.map((k) => `SUM(${k}) AS ${k}`).join(", ")} FROM usage WHERE user_id = ? AND day >= ? GROUP BY day ORDER BY day`
  ).bind(user.id, since).all();
  return json({ days: results });
}

async function deleteUser(env, user) {
  // Keys go first, and uploads insert only while the user still has a key, so an upload already
  // in flight can't leave rows behind.
  await env.DB.batch([
    ...["api_keys", "tokens", "device_codes", "usage"].map((t) => env.DB.prepare(`DELETE FROM ${t} WHERE user_id = ?`).bind(user.id)),
    env.DB.prepare("DELETE FROM users WHERE id = ?").bind(user.id),
  ]);
  return json({ deleted: true });
}

// ---- pages ----

async function activate(env, request, origin) {
  const data = await body(request);
  const code = String(data.user_code || "").toUpperCase().replace(/[^A-Z]/g, "");
  const email = String(data.email || "").trim();
  const formatted = `${code.slice(0, 4)}-${code.slice(4)}`;
  if (code.length !== 8 || !EMAIL.test(email)) return html(activateForm({ error: "Enter the 8-letter code from your terminal and your email.", email }), 400);
  const row = await env.DB.prepare("SELECT * FROM device_codes WHERE user_code = ? AND expires_at > ?").bind(formatted, now()).first();
  if (!row) {
    if (await limited(env, `badcode:${clientIp(request)}`, 30)) return html(activateForm({ error: "Too many tries. Wait an hour." }), 429);
    return html(activateForm({ error: "That code isn't valid or has expired. Run login again for a new one.", email }), 400);
  }
  if (row.user_id) return html(activateForm({ error: "That code is already confirmed. Go back to your terminal." }), 400);
  const tooMany = row.emails_sent >= 3 || (await limited(env, `mail-ip:${clientIp(request)}`, 20)) ||
    (await limited(env, `mail-to:${email.toLowerCase()}`, 5));
  if (tooMany) return html(activateForm({ error: "Too many tries. Wait an hour, then run login again." }), 429);
  await env.DB.prepare("UPDATE device_codes SET emails_sent = emails_sent + 1 WHERE device_code_hash = ?").bind(row.device_code_hash).run();
  // The account is created only when the link is confirmed, so typing an address creates nothing.
  const raw = await newToken(env, "confirm", null, CONFIRM_TTL, row.device_code_hash, email.toLowerCase());
  const link = `${origin}/confirm?t=${raw}`;
  if (env.ALLOW_UNVERIFIED === "1") return html(message("Confirm (test mode)", `<p><a href="${link}">Confirm sign-in</a></p>`));
  if (!(await sendConfirm(env, email, link, formatted))) return html(message("Couldn't send the email", "<p>Try again in a minute.</p>"), 502);
  return html(message("Check your email", "<p>We sent a link to finish signing in. It expires in 30 minutes.</p>"));
}

// GET only shows the code and a button, so a mail scanner opening the link changes nothing.
async function confirmShow(env, url) {
  const t = url.searchParams.get("t");
  const row = await takeToken(env, t, "confirm", false);
  const device = row && (await env.DB.prepare("SELECT * FROM device_codes WHERE device_code_hash = ? AND expires_at > ?").bind(row.ref, now()).first());
  if (!device || device.user_id) return html(message("Link expired", "<p>Run login again in your terminal for a new code.</p>"), 410);
  return html(confirmPage({ code: device.user_code, email: row.email, t }));
}

async function confirm(env, request) {
  const data = await body(request);
  const row = await takeToken(env, String(data.t || ""), "confirm");
  if (!row) return html(message("Link expired", "<p>Run login again in your terminal for a new code.</p>"), 410);
  const user = await findOrCreateUser(env, row.email, "cli");
  await env.DB.prepare("UPDATE users SET email_verified = 1 WHERE id = ?").bind(user.id).run();
  const r = await env.DB.prepare("UPDATE device_codes SET user_id = ? WHERE device_code_hash = ? AND user_id IS NULL AND expires_at > ?")
    .bind(user.id, row.ref, now()).run();
  if (!r.meta || !r.meta.changes) return html(message("Code expired", "<p>Your email is confirmed. Run login again to finish.</p>"), 410);
  return html(message("You're signed in", "<p>Go back to your terminal. You can close this tab.</p>"));
}

async function signup(env, request) {
  if (await limited(env, `signup:${clientIp(request)}`, 10)) return html(landing({ error: "Too many tries. Try again later." }), 429);
  const data = await body(request);
  const email = String(data.email || "").trim();
  if (!EMAIL.test(email)) return html(landing({ error: "Enter a valid email." }), 400);
  await findOrCreateUser(env, email, "web");
  return html(landing({ done: true }));
}

async function dashboardPage(env, request, url) {
  const t = url.searchParams.get("t");
  if (t) {
    const row = await takeToken(env, t, "link");
    if (!row) return html(message("Link expired", "<p>Run <code>account.py dashboard</code> again for a new link.</p>"), 410);
    const session = await newToken(env, "session", row.user_id, SESSION_TTL);
    return new Response(null, {
      status: 303,
      headers: { location: "/dashboard", "set-cookie": `te_session=${session}; Path=/; Max-Age=${SESSION_TTL}; HttpOnly; Secure; SameSite=Lax` },
    });
  }
  const user = await userFromSession(env, request);
  if (!user) return html(message("Sign in from your terminal", "<p>Run <code>python3 scripts/account.py dashboard</code>.</p>"), 401);
  if (!can(user, "dashboard")) return html(message("Not on this plan", ""), 403);
  const nonce = randomHex(16);
  return html(dashboard({ email: user.email, plan: user.plan, nonce }), 200, {}, nonce);
}

async function route(request, env, url) {
  const { pathname } = url;
  const method = request.method;
  if (pathname === "/" && method === "GET") return html(landing({}));
  if (pathname === "/signup" && method === "POST") return signup(env, request);
  if (pathname === "/activate" && method === "GET") return html(activateForm({}));
  if (pathname === "/activate" && method === "POST") return activate(env, request, url.origin);
  if (pathname === "/confirm" && method === "GET") return confirmShow(env, url);
  if (pathname === "/confirm" && method === "POST") return confirm(env, request);
  if (pathname === "/dashboard" && method === "GET") return dashboardPage(env, request, url);

  if (pathname === "/v1/device/start" && method === "POST") return deviceStart(env, request, url.origin);
  if (pathname === "/v1/device/poll" && method === "POST") return devicePoll(env, await body(request));

  if (pathname === "/v1/usage" && method === "GET") {
    const user = (await userFromKey(env, request)) || (await userFromSession(env, request));
    return user ? usageRead(env, user, url) : json({ error: "unauthorized" }, 401);
  }
  const user = await userFromKey(env, request);
  if (pathname.startsWith("/v1/") && !user) return json({ error: "unauthorized" }, 401);
  if (pathname === "/v1/me" && method === "GET") return json({ email: user.email, plan: user.plan, entitlements: entitlements(user.plan) });
  if (pathname === "/v1/me" && method === "DELETE") return deleteUser(env, user);
  if (pathname === "/v1/usage" && method === "POST") return usageUpload(env, user, await body(request));
  if (pathname === "/v1/dashboard-link" && method === "POST") {
    if (!can(user, "dashboard")) return json({ error: "not on this plan" }, 403);
    return json({ url: `${url.origin}/dashboard?t=${await newToken(env, "link", user.id, LINK_TTL)}` });
  }
  return pathname.startsWith("/v1/") ? json({ error: "not found" }, 404) : html(page("Not found", "<h1>Not found</h1>"), 404);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      return await route(request, env, url);
    } catch (e) {
      console.error(e);
      return url.pathname.startsWith("/v1/") ? json({ error: "server error" }, 500) : html(message("Something went wrong", ""), 500);
    }
  },
};
