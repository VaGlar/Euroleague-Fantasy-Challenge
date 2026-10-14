// Cloudflare Pages Function: the personal dashboard's ⭐ list -> the update's Telegram alerts.
//   POST /api/watch   {watch: {person_id: {at, price, x3, inj}}}   -> 202 (the watch workflow saves it)
// It starts .github/workflows/watch.yml, which keeps the list in the private data repo (elf/watch.py).
// Personal site only: it needs the GH_DISPATCH_TOKEN secret, set on that Pages project alone (HoopsLab
// answers 404), and a request that came through Cloudflare Access (the Access JWT header; 403 without).
// With the variables ACCESS_TEAM_DOMAIN (https://<team>.cloudflareaccess.com) and ACCESS_AUD (the Access
// application's audience tag) the JWT itself is checked: signature (the team's keys), audience, issuer,
// expiry. Without them only its presence is (enough while Access covers the whole site).
// Pages Functions don't get web/_headers: this one sets its own.
export const MAX_BYTES = 20_000;
export const MAX_PLAYERS = 60;
const PID_RE = /^\d{1,10}$/;
const DEFAULT_REPO = "VaGlar/Euroleague-Fantasy-Challenge";

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { "content-type": "application/json", "cache-control": "no-store", "x-content-type-options": "nosniff" },
});

// only the known fields, only player ids: the list is rebuilt, not passed through
export function cleanWatch(w) {
  if (!w || typeof w !== "object" || Array.isArray(w)) return null;
  const out = {};
  for (const [pid, e] of Object.entries(w)) {
    if (!PID_RE.test(pid) || !e || typeof e !== "object") continue;
    const n = (v) => (typeof v === "number" && Number.isFinite(v) ? Math.round(v * 100) / 100 : null);
    out[pid] = { at: typeof e.at === "string" && !Number.isNaN(Date.parse(e.at)) ? new Date(e.at).toISOString() : null,
      price: n(e.price), x3: n(e.x3), inj: !!e.inj };
    if (Object.keys(out).length >= MAX_PLAYERS) break;
  }
  return out;
}

const b64url = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(s.length / 4) * 4, "=")),
  (c) => c.charCodeAt(0));
let certs = null;                    // the team's public keys, kept for an hour per instance
async function accessKeys(team, fetchFn) {
  if (certs && certs.team === team && certs.until > Date.now()) return certs.keys;
  const r = await fetchFn(`${team}/cdn-cgi/access/certs`);
  if (!r.ok) throw new Error("certs " + r.status);
  certs = { team, keys: (await r.json()).keys || [], until: Date.now() + 3600_000 };
  return certs.keys;
}
// true when the token is a valid Access JWT for this application
export async function verifyAccess(token, { team, aud, now = Date.now() / 1000, fetchFn = fetch }) {
  try {
    const [h, p, sig] = String(token || "").split(".");
    if (!h || !p || !sig) return false;
    const head = JSON.parse(new TextDecoder().decode(b64url(h)));
    const body = JSON.parse(new TextDecoder().decode(b64url(p)));
    if (head.alg !== "RS256") return false;
    const jwk = (await accessKeys(team, fetchFn)).find((k) => k.kid === head.kid);
    if (!jwk) return false;
    const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64url(sig), new TextEncoder().encode(`${h}.${p}`));
    const auds = [].concat(body.aud || []);
    return ok && auds.includes(aud) && body.iss === team && typeof body.exp === "number" && body.exp > now;
  } catch (e) { return false; }
}

export async function onRequestPost({ request, env }) {
  if (!env.GH_DISPATCH_TOKEN) return json({ error: "not found" }, 404);
  const jwt = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!jwt) return json({ error: "forbidden" }, 403);
  if (env.ACCESS_TEAM_DOMAIN && env.ACCESS_AUD
      && !(await verifyAccess(jwt, { team: env.ACCESS_TEAM_DOMAIN.replace(/\/+$/, ""), aud: env.ACCESS_AUD }))) {
    return json({ error: "forbidden" }, 403);
  }
  const text = await request.text();
  if (text.length > MAX_BYTES) return json({ error: "too large" }, 413);
  let body;
  try { body = JSON.parse(text); } catch { return json({ error: "bad json" }, 400); }
  const watch = cleanWatch(body && body.watch);
  if (!watch) return json({ error: "bad watchlist" }, 400);
  const repo = env.GH_REPO || DEFAULT_REPO;
  const r = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/watch.yml/dispatches`, {
    method: "POST",
    headers: { authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`, accept: "application/vnd.github+json",
      "user-agent": "elf-dashboard", "x-github-api-version": "2022-11-28" },
    body: JSON.stringify({ ref: env.GH_REF || "main", inputs: { watch: JSON.stringify(watch) } }),
  });
  // GitHub's answer stays here (it may name the token's problem): the page only learns that it failed
  return r.status === 204 ? json({ ok: true, n: Object.keys(watch).length }, 202) : json({ error: "dispatch failed" }, 502);
}
