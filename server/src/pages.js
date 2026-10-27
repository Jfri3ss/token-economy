// HTML for the account server. No external assets; one stylesheet with light and dark tokens.

const INSTALL = "claude plugin marketplace add Jfri3ss/token-economy && claude plugin install token-economy@emmber";
const REPO = "https://github.com/Jfri3ss/token-economy";

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const CSS = `
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#57534e;--line:#e7e5e4;--card:#fff;--accent:#c2410c;--accent-fg:#fff;--bar:#fdba74}
@media (prefers-color-scheme:dark){:root{--bg:#0c0a09;--fg:#f5f5f4;--muted:#a8a29e;--line:#292524;--card:#1c1917;--accent:#fb923c;--accent-fg:#0c0a09;--bar:#9a3412}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:48px 16px}h1{font-size:2rem;line-height:1.2;margin:0 0 12px}h2{font-size:1.15rem;margin:32px 0 8px}
p,li{color:var(--muted)}a{color:var(--accent)}code,pre{font:14px ui-monospace,SFMono-Regular,Menlo,monospace}
pre{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;overflow-x:auto;white-space:pre-wrap;word-break:break-all;color:var(--fg)}
form{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}input{flex:1 1 220px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);font:inherit}
button{padding:10px 16px;border:0;border-radius:8px;background:var(--accent);color:var(--accent-fg);font:inherit;font-weight:600;cursor:pointer}
button:hover,button:focus-visible{filter:brightness(1.1);outline:2px solid var(--accent);outline-offset:2px}
.err{color:#dc2626}.ok{color:var(--fg)}.small{font-size:.875rem}
table{width:100%;border-collapse:collapse;font-size:.9rem}th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}
.bar{display:inline-block;height:8px;background:var(--bar);border-radius:4px;vertical-align:middle;margin-right:6px}
.wrap{overflow-x:auto}footer{margin-top:48px;font-size:.85rem;color:var(--muted)}
`;

export function page(title, inner) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title><style>${CSS}</style></head><body><main>${inner}
<footer>token-economy · free and open source (MIT) · © 2026 Emmber, Inc. · <a href="${REPO}">GitHub</a> · <a href="${REPO}/blob/main/PRIVACY.md">Privacy</a></footer>
</main></body></html>`;
}

export function message(title, inner) {
  return page(title, `<h1>${esc(title)}</h1>${inner}`);
}

export function landing({ error, done }) {
  return page("token-economy", `
<h1>Spend fewer Claude Code tokens on the same work.</h1>
<p>token-economy is a free Claude Code plugin. It sends each task to the cheapest model that can do it well, keeps huge tool output out of your context, sizes the end-of-turn check to the change, and shows you where your tokens went.</p>
<h2>Install</h2>
<pre>${esc(INSTALL)}</pre>
<p class="small">Then start a new Claude Code session. No account needed.</p>
<h2>Free account (optional)</h2>
<p>Sign in from your terminal to see your usage over time, across machines. Only daily counts are uploaded, and only if you turn uploads on. No prompts, code or file names leave your machine.</p>
<pre>python3 "$(ls -d ~/.claude/plugins/cache/emmber/token-economy/*/ | tail -1)scripts/account.py" login --upload</pre>
<h2>Team features are coming</h2>
<p>Leave your email for team dashboards and shared settings.</p>
${done ? `<p class="ok">You're on the list.</p>` : `<form method="post" action="/signup">
<input type="email" name="email" required placeholder="you@company.com" aria-label="Email">
<button type="submit">Keep me posted</button></form>${error ? `<p class="err">${esc(error)}</p>` : ""}`}
`);
}

export function activateForm({ error, email }) {
  return page("Sign in to token-economy", `
<h1>Sign in to token-economy</h1>
<p>Enter the code your terminal shows and your email. We'll email you a link to finish.</p>
<form method="post" action="/activate">
<input name="user_code" required placeholder="ABCD-EFGH" autocomplete="off" autocapitalize="characters" aria-label="Code from your terminal">
<input type="email" name="email" required placeholder="you@company.com" value="${esc(email)}" aria-label="Email">
<button type="submit">Send link</button></form>
${error ? `<p class="err">${esc(error)}</p>` : ""}`);
}

export function confirmPage({ code, email, t }) {
  return page("Confirm sign-in", `
<h1>Confirm sign-in</h1>
<p>This signs in a terminal as <strong>${esc(email)}</strong>.</p>
<p>Only continue if your terminal shows this code:</p>
<pre>${esc(code)}</pre>
<form method="post" action="/confirm"><input type="hidden" name="t" value="${esc(t)}">
<button type="submit">Sign in that terminal</button></form>
<p class="small">If you didn't run login, close this tab and nothing happens.</p>`);
}

export function dashboard({ email, plan, nonce }) {
  return page("Your token usage", `
<h1>Your token usage</h1>
<p class="small">${esc(email)} · ${esc(plan)} plan</p>
<p>Weekly totals from the numbers your machines uploaded. Context per step is the main cost: every step re-sends the whole conversation.</p>
<div class="wrap"><table><thead><tr><th>Week of</th><th>Sessions</th><th>Steps</th><th>Context K per step</th><th>Tool KB per step</th><th>Guard blocks</th><th>Overridden</th></tr></thead>
<tbody id="rows"><tr><td colspan="7">Loading…</td></tr></tbody></table></div>
<p class="small">"Overridden" counts blocks that were rerun as written with #full, a sign the guard was wrong. Work differs week to week, so compare like with like.</p>
<script nonce="${esc(nonce)}">
(async () => {
  const tbody = document.getElementById("rows");
  const r = await fetch("/v1/usage?days=180", { credentials: "same-origin" });
  if (!r.ok) { tbody.innerHTML = "<tr><td colspan='7'>Couldn't load your numbers.</td></tr>"; return; }
  const { days } = await r.json();
  if (!days.length) { tbody.innerHTML = "<tr><td colspan='7'>Nothing uploaded yet. Run account.py sync.</td></tr>"; return; }
  const weeks = new Map();
  for (const d of days) {
    const t = new Date(d.day + "T00:00:00Z"); t.setUTCDate(t.getUTCDate() - ((t.getUTCDay() + 6) % 7));
    const k = t.toISOString().slice(0, 10);
    const w = weeks.get(k) || { sessions: 0, steps: 0, reread: 0, tool_bytes: 0, denials: 0, overrides: 0 };
    for (const f in w) w[f] += d[f] || 0;
    weeks.set(k, w);
  }
  const list = [...weeks].sort((a, b) => b[0].localeCompare(a[0]));
  const max = Math.max(...list.map(([, w]) => w.steps ? w.reread / w.steps : 0), 1);
  tbody.textContent = "";
  for (const [k, w] of list) {
    const ctx = w.steps ? w.reread / w.steps / 1000 : 0;
    const tr = document.createElement("tr");
    const cells = [k, w.sessions, w.steps, null, w.steps ? (w.tool_bytes / w.steps / 1024).toFixed(1) : "0", w.denials, w.overrides];
    cells.forEach((v, i) => {
      const td = document.createElement("td");
      if (i === 3) { const b = document.createElement("span"); b.className = "bar"; b.style.width = Math.round(60 * ctx * 1000 / max) + "px"; td.append(b, ctx.toFixed(0)); }
      else td.textContent = v;
      tr.append(td);
    });
    tbody.append(tr);
  }
})();
</script>`);
}
