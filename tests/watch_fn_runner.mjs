// Runs functions/api/watch.js on cases from stdin with a stand-in for GitHub's API (fetch), and prints
// each response and what was dispatched (used by tests/test_watch.py).
// A case: {env, headers, body (string)}.
const { onRequestPost } = await import("../functions/api/watch.js");
let buf = "";
for await (const d of process.stdin) buf += d;
const out = [];
for (const c of JSON.parse(buf)) {
  const sent = [];
  globalThis.fetch = async (url, init) => { sent.push({ url, body: JSON.parse(init.body), auth: init.headers.authorization });
    return new Response(null, { status: c.github ?? 204 }); };
  const request = new Request("https://site.example/api/watch", { method: "POST", headers: c.headers || {}, body: c.body ?? "" });
  const res = await onRequestPost({ request, env: c.env || {} });
  out.push({ status: res.status, body: await res.json(), sent, nosniff: res.headers.get("x-content-type-options") });
}
process.stdout.write(JSON.stringify(out));
