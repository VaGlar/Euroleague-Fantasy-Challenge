// Runs the pieces of the 14/10 tester findings in node and prints what they return (used by
// tests/test_review_fixes.py): the sync code typed on a Greek keyboard, the team check of the sync,
// nosniff on the sync's answers, the errors table's clean-up, and the Access JWT check of /api/watch.
const sync = await import("../functions/api/sync/[[path]].js");
const errors = await import("../functions/api/errors.js");
const watch = await import("../functions/api/watch.js");

let buf = "";
for await (const d of process.stdin) buf += d;
const c = JSON.parse(buf);
const out = {};

out.codes = c.codes.map((s) => sync.cleanCode(s));
out.teams = c.teams.map((t) => sync.validTeam(t));
out.nosniff = (await sync.onRequest({ request: new Request("https://x.example/api/sync"), env: {}, params: {} }))
  .headers.get("x-content-type-options");

// errors: a D1 that records the statements; the first error of a day deletes days older than KEEP_DAYS
const sql = [];
const db = { prepare(q) { const s = q.replace(/\s+/g, " ").trim(); return { a: [], bind(...a) { this.a = a; return this; },
  async run() { sql.push([s, this.a]); return {}; },
  async first() { sql.push([s, this.a]); return s.startsWith("SELECT") ? { c: 1 } : { n: 1 }; } }; } };
const post = new Request("https://x.example/api/errors", { method: "POST", body: JSON.stringify({ msg: "boom", src: "a.js", line: 1 }) });
out.errorsStatus = (await errors.onRequestPost({ request: post, env: { SYNC_DB: db } })).status;
out.errorsDeletes = sql.filter(([s]) => s.startsWith("DELETE")).map(([s, a]) => [s, a[0]]);
out.keepDays = errors.KEEP_DAYS;

// Access JWT: a key of our own stands for the team's
const team = "https://team.cloudflareaccess.com", aud = "aud-tag";
const kp = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]),
  hash: "SHA-256" }, true, ["sign", "verify"]);
const jwk = { ...(await crypto.subtle.exportKey("jwk", kp.publicKey)), kid: "k1" };
const b64 = (u8) => Buffer.from(u8).toString("base64url");
const enc = (o) => b64(new TextEncoder().encode(JSON.stringify(o)));
async function token(body, head = { alg: "RS256", kid: "k1" }) {
  const data = `${enc(head)}.${enc(body)}`;
  const sig = new Uint8Array(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", kp.privateKey, new TextEncoder().encode(data)));
  return `${data}.${b64(sig)}`;
}
const now = Math.floor(Date.now() / 1000);
const good = { aud: [aud], iss: team, exp: now + 600 };
const fetchFn = async (url) => (url === `${team}/cdn-cgi/access/certs` ? new Response(JSON.stringify({ keys: [jwk] })) : new Response("", { status: 404 }));
const valid = await token(good);
const cases = {
  valid,
  wrong_aud: await token({ ...good, aud: ["other"] }),
  wrong_iss: await token({ ...good, iss: "https://evil.cloudflareaccess.com" }),
  expired: await token({ ...good, exp: now - 10 }),
  unknown_kid: await token(good, { alg: "RS256", kid: "k2" }),
  alg_none: `${enc({ alg: "none", kid: "k1" })}.${enc(good)}.`,
  tampered: valid.replace(/\.([^.]+)\./, (m, p) => `.${enc({ ...good, aud: [aud, "x"] })}.`),
  garbage: "jwt",
};
out.verify = {};
for (const [k, t] of Object.entries(cases)) out.verify[k] = await watch.verifyAccess(t, { team, aud, fetchFn });

// the endpoint: with ACCESS_* set the token is checked; without them only its presence (as before)
globalThis.fetch = async (url, init) => (String(url).includes("cloudflareaccess.com") ? fetchFn(String(url))
  : new Response(null, { status: 204 }));
const call = async (jwt, env) => (await watch.onRequestPost({ env: { GH_DISPATCH_TOKEN: "t", ...env },
  request: new Request("https://x.example/api/watch", { method: "POST", headers: { "Cf-Access-Jwt-Assertion": jwt },
    body: JSON.stringify({ watch: { "123": { at: "2026-10-14T10:00:00Z", price: 5 } } }) }) })).status;
const ACCESS = { ACCESS_TEAM_DOMAIN: team + "/", ACCESS_AUD: aud };
out.endpoint = { valid: await call(valid, ACCESS), forged: await call("jwt", ACCESS), expired: await call(cases.expired, ACCESS),
  no_config: await call("jwt", {}) };
process.stdout.write(JSON.stringify(out));
