// Cloudflare Pages Function: the pages' JavaScript errors, so a bug on a user's phone reaches the owner.
//   POST /api/errors   {msg, src, line, tab, edition}   -> 204
// Counted per day and error in D1 (binding SYNC_DB, table `errors`); the first time an error shows up on a
// day it goes to the owner's Telegram (secrets TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID on the Pages project;
// without them it is only counted). Nothing personal: the error's text (cut), the file and line, the tab.
// Limit: ERR_LIMIT reports per IP and hour (the IP only as a salted hash, as in the sync), MAX_ALERTS a day.
// Kept KEEP_DAYS days: the first new error of a day deletes older ones.
// Pages Functions don't get web/_headers: this one sets its own.
export const MAX_BYTES = 2_000;
export const ERR_LIMIT = 30;
export const MAX_ALERTS = 20;
export const KEEP_DAYS = 30;            // the counts are kept this long, then deleted
const HOUR = 3600;

const done = (status = 204) => new Response(null, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" } });
const clip = (s, n) => String(s ?? "").replace(/[\u0000-\u001f]/g, " ").slice(0, n);

let ready = false;
async function tables(db) {
  if (ready) return;
  await db.prepare(`CREATE TABLE IF NOT EXISTS errors (day TEXT NOT NULL, k TEXT NOT NULL, msg TEXT NOT NULL,
    src TEXT, tab TEXT, n INTEGER NOT NULL, PRIMARY KEY (day, k))`).run();
  await db.prepare("CREATE TABLE IF NOT EXISTS hits (k TEXT PRIMARY KEY, n INTEGER NOT NULL, until INTEGER NOT NULL)").run();
  ready = true;
}

async function sha(text) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(d).slice(0, 12), (x) => x.toString(16).padStart(2, "0")).join("");
}

export async function onRequestPost({ request, env }) {
  const db = env.SYNC_DB;
  if (!db) return done();                                   // nowhere to count (the personal site): ignore
  const text = await request.text();
  if (text.length > MAX_BYTES) return done(413);
  let e;
  try { e = JSON.parse(text); } catch { return done(400); }
  if (!e || typeof e !== "object" || !e.msg) return done(400);
  await tables(db);
  const now = Math.floor(Date.now() / 1000), hour = Math.floor(now / HOUR);
  const ip = await sha(`${env.SYNC_SALT || "hoopslab-sync"}|${request.headers.get("CF-Connecting-IP") || "local"}`);
  const hit = await db.prepare(`INSERT INTO hits (k, n, until) VALUES (?, 1, ?)
    ON CONFLICT(k) DO UPDATE SET n = n + 1 RETURNING n`).bind(`ERR:${ip}:${hour}`, (hour + 1) * HOUR).first();
  if ((hit?.n ?? 0) > ERR_LIMIT) return done(429);

  const msg = clip(e.msg, 200), src = clip(`${e.src || ""}:${e.line || ""}`, 80), tab = clip(e.tab, 20);
  const edition = e.edition === "public" ? "HoopsLab" : "προσωπική";
  const day = new Date().toISOString().slice(0, 10);
  const k = await sha(`${msg}|${src}`);
  const row = await db.prepare(`INSERT INTO errors (day, k, msg, src, tab, n) VALUES (?, ?, ?, ?, ?, 1)
    ON CONFLICT(day, k) DO UPDATE SET n = n + 1 RETURNING n`).bind(day, k, msg, src, tab).first();
  // a new error of the day: the old days go (and the hour counters that are over); never fails the report
  if (row?.n === 1) {
    const old = new Date(Date.now() - KEEP_DAYS * 86400_000).toISOString().slice(0, 10);
    try {
      await db.prepare("DELETE FROM errors WHERE day < ?").bind(old).run();
      await db.prepare("DELETE FROM hits WHERE until < ?").bind(now).run();
    } catch (err) { /* the next new error tries again */ }
  }
  if (row?.n === 1 && env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID) {
    const today = await db.prepare("SELECT COUNT(*) AS c FROM errors WHERE day = ?").bind(day).first();
    if ((today?.c ?? 0) <= MAX_ALERTS) {
      const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
      await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, parse_mode: "HTML", disable_web_page_preview: true,
          text: `🐞 <b>Σφάλμα στη σελίδα</b> (${edition}, tab ${esc(tab) || "–"})\n<code>${esc(msg)}</code>\n${esc(src)}` }),
      }).catch(() => {});
    }
  }
  return done();
}
