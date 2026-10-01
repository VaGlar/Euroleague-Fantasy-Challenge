// Cloudflare Pages Function: a team kept in step across a user's devices (public edition).
// No accounts: a long random code is the key; whoever has it reads and writes that team.
//   POST /api/sync            {data}            -> {code, rev, updated_at}   a new code for this team
//   GET  /api/sync/<code>                       -> {data, rev, updated_at}   (404: unknown code)
//   PUT  /api/sync/<code>     {data, rev}       -> {rev, updated_at}         (409 + the stored copy when
//        rev isn't the stored one: another device wrote in between; the client decides who wins)
// Storage: D1 (binding SYNC_DB). SQL on purpose: the table moves to Postgres (Supabase) as it is, and
// user_id is there for when accounts come; the page only knows this endpoint.
// Without the binding (the personal edition, or before it is set up) every call answers 503.
export const ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";   // no 0/O, 1/I/L: read aloud or typed
export const CODE_LEN = 12;                                   // 31^12 ≈ 8·10^17: not guessable
export const MAX_BYTES = 200_000;
const CODE_RE = new RegExp(`^[${ALPHABET}]{${CODE_LEN}}$`);

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { "content-type": "application/json", "cache-control": "no-store" },
});

export function newCode() {
  const b = crypto.getRandomValues(new Uint8Array(CODE_LEN));
  return Array.from(b, (x) => ALPHABET[x % ALPHABET.length]).join("");
}
// "abcd-efgh-jkmn" as typed -> "ABCDEFGHJKMN"
export const cleanCode = (s) => String(s || "").toUpperCase().replace(/[^A-Z0-9]/g, "");

// a team as the page keeps it: an object with up to 15 players (11 + room for the game's rules)
function validTeam(d) {
  return d && typeof d === "object" && !Array.isArray(d) && Array.isArray(d.players) && d.players.length <= 15
    && d.players.every((p) => p && Number.isFinite(Number(p.id)));
}

let ready = false;
async function table(db) {
  if (ready) return;
  await db.prepare(`CREATE TABLE IF NOT EXISTS teams (code TEXT PRIMARY KEY, data TEXT NOT NULL,
    rev INTEGER NOT NULL, updated_at TEXT NOT NULL, user_id TEXT)`).run();
  ready = true;
}

async function body(request) {
  const text = await request.text();
  if (text.length > MAX_BYTES) return { error: json({ error: "too large" }, 413) };
  try {
    const b = JSON.parse(text);
    if (!validTeam(b && b.data)) return { error: json({ error: "bad team" }, 400) };
    return { b, text: JSON.stringify(b.data) };
  } catch { return { error: json({ error: "bad json" }, 400) }; }
}

export async function onRequest({ request, env, params }) {
  const db = env.SYNC_DB;
  if (!db) return json({ error: "sync not set up" }, 503);
  await table(db);
  const path = [].concat(params.path || []);
  const now = new Date().toISOString();

  if (!path.length) {
    if (request.method !== "POST") return json({ error: "method" }, 405);
    const { b, text, error } = await body(request);
    if (error) return error;
    for (let i = 0; i < 3; i++) {                    // a clash of random codes: practically never
      const code = newCode();
      const r = await db.prepare("INSERT OR IGNORE INTO teams (code, data, rev, updated_at) VALUES (?, ?, 1, ?)")
        .bind(code, text, now).run();
      if (r.meta?.changes) return json({ code, rev: 1, updated_at: now }, 201);
    }
    return json({ error: "try again" }, 500);
  }

  const code = cleanCode(path[0]);
  if (path.length > 1 || !CODE_RE.test(code)) return json({ error: "bad code" }, 400);
  const row = await db.prepare("SELECT data, rev, updated_at FROM teams WHERE code = ?").bind(code).first();

  if (request.method === "GET") {
    if (!row) return json({ error: "unknown code" }, 404);
    return json({ data: JSON.parse(row.data), rev: row.rev, updated_at: row.updated_at });
  }
  if (request.method === "PUT") {
    if (!row) return json({ error: "unknown code" }, 404);
    const { b, text, error } = await body(request);
    if (error) return error;
    if (Number(b.rev) !== row.rev) {
      return json({ error: "conflict", data: JSON.parse(row.data), rev: row.rev, updated_at: row.updated_at }, 409);
    }
    // the rev in the WHERE: two devices writing at the same instant can't both win
    const r = await db.prepare("UPDATE teams SET data = ?, rev = rev + 1, updated_at = ? WHERE code = ? AND rev = ?")
      .bind(text, now, code, row.rev).run();
    if (!r.meta?.changes) {
      const cur = await db.prepare("SELECT data, rev, updated_at FROM teams WHERE code = ?").bind(code).first();
      return json({ error: "conflict", data: JSON.parse(cur.data), rev: cur.rev, updated_at: cur.updated_at }, 409);
    }
    return json({ rev: row.rev + 1, updated_at: now });
  }
  return json({ error: "method" }, 405);
}
