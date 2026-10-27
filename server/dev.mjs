// Local runner for tests and previews: the Worker on Node's HTTP server, D1 replaced by node:sqlite.
// node server/dev.mjs [--port 8787]   (prints "listening <port>"; confirm links show on the page)
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import worker from "./src/worker.js";

const here = path.dirname(fileURLToPath(import.meta.url));

export function fakeD1(file = ":memory:") {
  const db = new DatabaseSync(file);
  db.exec(fs.readFileSync(path.join(here, "schema.sql"), "utf8"));
  const norm = (args) => args.map((a) => (a === undefined ? null : a));
  const stmt = (sql, args = []) => ({
    bind: (...a) => stmt(sql, norm(a)),
    first: async () => db.prepare(sql).get(...args) ?? null,
    all: async () => ({ results: db.prepare(sql).all(...args) }),
    run: async () => {
      const r = db.prepare(sql).run(...args);
      return { meta: { changes: Number(r.changes) } };
    },
  });
  return { prepare: (sql) => stmt(sql), batch: async (list) => { const out = []; for (const s of list) out.push(await s.run()); return out; }, raw: db };
}

export function serve(env, port = 0) {
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const request = new Request(`http://${req.headers.host}${req.url}`, {
      method: req.method, headers: req.headers, body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks),
    });
    const response = await worker.fetch(request, env);
    const headers = Object.fromEntries(response.headers);
    res.writeHead(response.status, headers);
    res.end(Buffer.from(await response.arrayBuffer()));
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const i = process.argv.indexOf("--port");
  const server = await serve({ DB: fakeD1(), ALLOW_UNVERIFIED: "1" }, i > 0 ? Number(process.argv[i + 1]) : 0);
  console.log(`listening ${server.address().port}`);
}
