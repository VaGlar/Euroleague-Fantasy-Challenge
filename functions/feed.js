// Cloudflare Pages Function: /feed?u=<substack or basketnews url>
// Some sites (Substack, BasketNews) refuse requests from GitHub Actions' datacenter IPs; the
// pipeline falls back to fetching them through this function. Allow-listed hosts
// only, so it can't be used as an open proxy.
const ALLOWED = [/\.substack\.com$/, /(^|\.)basketnews\.com$/];

export async function onRequestGet({ request }) {
  const u = new URL(request.url).searchParams.get("u") || "";
  let target;
  try { target = new URL(u); } catch { return new Response("bad url", { status: 400 }); }
  if (target.protocol !== "https:" || !ALLOWED.some((re) => re.test(target.hostname))) {
    return new Response("host not allowed", { status: 403 });
  }
  const r = await fetch(target.toString(), {
    // a browser's headers: BasketNews (Cloudflare) refuses clients that don't look like one
    headers: {
      "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
      accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "accept-language": "en-US,en;q=0.9",
    },
    cf: { cacheTtl: 900, cacheEverything: true },
  });
  return new Response(r.body, {
    status: r.status,
    headers: { "content-type": r.headers.get("content-type") || "text/plain" },
  });
}
