// Runs the sync Pages Function (functions/api/sync/[[path]].js) on a list of requests from stdin,
// against an in-memory stand-in for D1 (only the statements the function uses), and prints each
// response (used by tests/test_sync.py). A case: {requests: [{method, path, body}], db: false?};
// "{code}" in a path is the code the case's first POST got back, "{dashed}" the same as a person types it
const { onRequest } = await import("../functions/api/sync/[[path]].js");

function fakeD1() {
  const rows = new Map();
  return {
    rows,
    prepare(sql) {
      const s = sql.replace(/\s+/g, " ").trim();
      return {
        args: [],
        bind(...a) { this.args = a; return this; },
        async run() {
          const a = this.args;
          if (s.startsWith("CREATE TABLE")) return { meta: { changes: 0 } };
          if (s.startsWith("INSERT OR IGNORE")) {
            if (rows.has(a[0])) return { meta: { changes: 0 } };
            rows.set(a[0], { data: a[1], rev: 1, updated_at: a[2] });
            return { meta: { changes: 1 } };
          }
          if (s.startsWith("UPDATE teams")) {
            const r = rows.get(a[2]);
            if (!r || r.rev !== a[3]) return { meta: { changes: 0 } };
            rows.set(a[2], { data: a[0], rev: r.rev + 1, updated_at: a[1] });
            return { meta: { changes: 1 } };
          }
          throw new Error("unexpected SQL: " + s);
        },
        async first() {
          if (!s.startsWith("SELECT")) throw new Error("unexpected SQL: " + s);
          const r = rows.get(this.args[0]);
          return r ? { ...r } : null;
        },
      };
    },
  };
}

let buf = "";
for await (const d of process.stdin) buf += d;
const out = [];
for (const c of JSON.parse(buf)) {
  const db = c.db === false ? undefined : fakeD1();
  const res = [];
  let code = "";
  for (const q0 of c.requests) {
    const dashed = code.toLowerCase().replace(/(....)(....)(....)/, "$1-$2-$3");
    const q = { ...q0, path: q0.path.replace("{code}", code).replace("{dashed}", dashed) };
    const parts = q.path.replace(/^\/api\/sync\/?/, "").split("/").filter(Boolean);
    const request = new Request("https://hoopslab.example" + q.path, {
      method: q.method, body: q.body === undefined ? undefined : (typeof q.body === "string" ? q.body : JSON.stringify(q.body)),
    });
    const r = await onRequest({ request, env: { SYNC_DB: db }, params: parts.length ? { path: parts } : {} });
    let b = null;
    try { b = await r.json(); } catch { b = null; }
    if (q.method === "POST" && r.status === 201 && !code) code = b.code;
    res.push({ status: r.status, body: b });
  }
  out.push(res);
}
process.stdout.write(JSON.stringify(out));
