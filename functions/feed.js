// Cloudflare Pages Function: /feed?u=<substack or basketnews url>
// Some sites (Substack, BasketNews) refuse requests from GitHub Actions' datacenter IPs; the
// pipeline falls back to fetching them through this function. Allow-listed hosts
// only, so it can't be used as an open proxy.
const ALLOWED = [/\.substack\.com$/, /(^|\.)basketnews\.com$/];

export async function onRequestGet({ request }) {
  const u = new URL(request.url).searchParams.get("u") || "";
  let target;
  try { target = new URL(u); } catch { return text("bad url", 400); }
  if (!allowed(target)) return text("host not allowed", 403);
  const r = await fetch(target.toString(), {
    // a browser's headers: BasketNews (Cloudflare) refuses clients that don't look like one
    headers: {
      "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
      accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "accept-language": "en-US,en;q=0.9",
    },
    cf: { cacheTtl: 900, cacheEverything: true },
  });
  // fetch follows redirects: a Substack with a custom domain ends outside the list, so check where it ended
  let final;
  try { final = new URL(r.url || target.toString()); } catch { return text("host not allowed", 403); }
  if (!allowed(final)) return text("host not allowed", 403);
  return text(r.body, r.status);
}

const allowed = (url) => url.protocol === "https:" && ALLOWED.some((re) => re.test(url.hostname));

// always plain text that can't run as a page of this site: the pipeline only reads the bytes, and
// web/_headers doesn't reach Functions, so the headers are set here
const text = (body, status) => new Response(body, {
  status,
  headers: {
    "content-type": "text/plain; charset=utf-8",
    "x-content-type-options": "nosniff",
    "content-security-policy": "sandbox",
  },
});
