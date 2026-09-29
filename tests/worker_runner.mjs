// Runs worker/src/index.js (the Telegram bot + hourly schedule) on JSON cases from stdin,
// with fetch and the clock faked, and prints every outgoing call (used by tests/test_worker.py).
//
// case: { now: ISO UTC, env: {...}, data: { "report.json": {...}, "predictions.json": {...} },
//         dispatchStatus: 204, event: { kind: "scheduled" } | { kind: "fetch", method, path,
//         headers, body } }
// out:  { status, body, calls: [{ kind: "tg", method, body } | { kind: "dispatch", workflow,
//         inputs } | { kind: "data", name }] }
const REAL_DATE = Date;
let NOW = 0;
globalThis.Date = class extends REAL_DATE {
  constructor(...a) { super(...(a.length ? a : [NOW])); }
  static now() { return NOW; }
};

const { default: worker } = await import("../worker/src/index.js");

let buf = "";
for await (const d of process.stdin) buf += d;
const out = [];
for (const c of JSON.parse(buf)) {
  NOW = REAL_DATE.parse(c.now || "2026-10-01T09:00:00Z");
  const calls = [];
  globalThis.fetch = async (url, opts = {}) => {
    url = String(url);
    const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status });
    if (url.startsWith("https://api.telegram.org/")) {
      calls.push({ kind: "tg", method: url.split("/").pop(), body: JSON.parse(opts.body) });
      return json({ ok: true });
    }
    const m = url.match(/actions\/workflows\/([^/]+)\/dispatches$/);
    if (m) {
      const body = JSON.parse(opts.body);
      calls.push({ kind: "dispatch", workflow: m[1], ref: body.ref, inputs: body.inputs,
        auth: opts.headers.authorization });
      return new Response(c.dispatchStatus === 204 || c.dispatchStatus == null ? null : "denied",
        { status: c.dispatchStatus ?? 204 });
    }
    if (c.env?.DATA_URL && url.startsWith(c.env.DATA_URL)) {
      const name = url.slice(c.env.DATA_URL.length + 1).split("?")[0];
      calls.push({ kind: "data", name });
      if (!(name in (c.data || {}))) return json({ error: "missing" }, 404);
      return json(c.data[name]);
    }
    throw new Error(`unexpected fetch ${url}`);
  };
  const ev = c.event || { kind: "scheduled" };
  let status = null, body = null, error = null;
  try {
    if (ev.kind === "scheduled") {
      await worker.scheduled({}, c.env || {}, {});
    } else {
      const init = { method: ev.method || "POST", headers: ev.headers || {} };
      if (ev.body !== undefined) init.body = JSON.stringify(ev.body);
      const r = await worker.fetch(new Request(`https://bot.example${ev.path || "/telegram"}`, init), c.env || {});
      status = r.status;
      body = await r.text();
    }
  } catch (e) {
    error = String(e && e.message);
  }
  out.push({ status, body, error, calls });
}
process.stdout.write(JSON.stringify(out));
