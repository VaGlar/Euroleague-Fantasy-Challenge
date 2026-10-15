// Runs functions/feed.js on cases from stdin with a stand-in for fetch (nothing leaves the machine) and
// prints each response (used by tests/test_feed_fn.py). A case: {u, upstream: {status, type, body, url}}:
// the upstream answer the stand-in gives; `url` is where it ended (a redirect followed by fetch).
const { onRequestGet } = await import("../functions/feed.js");
let buf = "";
for await (const d of process.stdin) buf += d;
const out = [];
for (const c of JSON.parse(buf)) {
  const asked = [];
  globalThis.fetch = async (url) => {
    asked.push(String(url));
    const up = c.upstream || {};
    const r = new Response(up.body ?? "<rss/>", { status: up.status ?? 200, headers: { "content-type": up.type ?? "application/rss+xml" } });
    Object.defineProperty(r, "url", { value: up.url ?? String(url) });     // where fetch ended after redirects
    return r;
  };
  const request = new Request("https://site.example/feed" + (c.u == null ? "" : "?u=" + encodeURIComponent(c.u)));
  const res = await onRequestGet({ request });
  out.push({ status: res.status, type: res.headers.get("content-type"), csp: res.headers.get("content-security-policy"),
    nosniff: res.headers.get("x-content-type-options"), body: (await res.text()).slice(0, 60), asked });
}
process.stdout.write(JSON.stringify(out));
