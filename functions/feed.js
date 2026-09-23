// Cloudflare Pages Function: /feed?u=<substack url>
// Some sites (Substack) refuse requests from GitHub Actions' datacenter IPs; the
// pipeline falls back to fetching them through this function. Allow-listed hosts
// only, so it can't be used as an open proxy.
const ALLOWED = [/\.substack\.com$/];

export async function onRequestGet({ request }) {
  const u = new URL(request.url).searchParams.get("u") || "";
  let target;
  try { target = new URL(u); } catch { return new Response("bad url", { status: 400 }); }
  if (target.protocol !== "https:" || !ALLOWED.some((re) => re.test(target.hostname))) {
    return new Response("host not allowed", { status: 403 });
  }
  const r = await fetch(target.toString(), {
    headers: { "user-agent": "Mozilla/5.0 (compatible; elf-feed/1.0)", accept: "*/*" },
    cf: { cacheTtl: 900, cacheEverything: true },
  });
  return new Response(r.body, {
    status: r.status,
    headers: { "content-type": r.headers.get("content-type") || "text/plain" },
  });
}
