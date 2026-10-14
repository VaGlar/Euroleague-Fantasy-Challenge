// Runs functions/api/errors.js on cases from stdin against an in-memory D1 and a stand-in for Telegram,
// and prints each response and what was sent (used by tests/test_errors_fn.py).
// A case: {env, posts: [{body, ip}]}; env.SYNC_DB true = a database.
const { onRequestPost } = await import("../functions/api/errors.js");

function fakeD1() {
  const hits = new Map(), errors = new Map();
  return {
    prepare(sql) {
      const s = sql.replace(/\s+/g, " ").trim();
      return {
        args: [],
        bind(...a) { this.args = a; return this; },
        async run() { if (s.startsWith("CREATE TABLE")) return {}; throw new Error("unexpected SQL: " + s); },
        async first() {
          const a = this.args;
          if (s.startsWith("INSERT INTO hits")) { const h = hits.get(a[0]) || { n: 0 }; h.n++; hits.set(a[0], h); return { n: h.n }; }
          if (s.startsWith("INSERT INTO errors")) {
            const key = a[0] + "|" + a[1], e = errors.get(key) || { n: 0, msg: a[2] }; e.n++; errors.set(key, e); return { n: e.n };
          }
          if (s.startsWith("SELECT COUNT")) return { c: [...errors.keys()].filter((k) => k.startsWith(a[0] + "|")).length };
          throw new Error("unexpected SQL: " + s);
        },
      };
    },
  };
}

let buf = "";
for await (const d of process.stdin) buf += d;
const out = [];
for (const c of JSON.parse(buf)) {
  const sent = [];
  globalThis.fetch = async (url, init) => { sent.push({ url: url.replace(/bot[^/]+/, "bot***"), body: JSON.parse(init.body) }); return new Response("{}"); };
  const env = { ...(c.env || {}), SYNC_DB: c.env && c.env.SYNC_DB ? fakeD1() : undefined };
  const res = [];
  for (const p of c.posts) {
    const request = new Request("https://hoopslab.example/api/errors", { method: "POST",
      headers: { "CF-Connecting-IP": p.ip || "203.0.113.1" }, body: typeof p.body === "string" ? p.body : JSON.stringify(p.body) });
    res.push((await onRequestPost({ request, env })).status);
  }
  out.push({ status: res, sent });
}
process.stdout.write(JSON.stringify(out));
