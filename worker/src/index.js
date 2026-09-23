// Cloudflare Worker: 11:00 (Athens) game-day notifications + Telegram bot commands.
//
// Secrets (wrangler secret put): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WEBHOOK_SECRET
// Vars (wrangler.toml): DATA_URL (base URL of data/public), DASHBOARD_URL
//
// Two UTC crons (08:00 and 09:00) cover summer/winter time; the handler only
// acts when it is 11:xx in Athens, so exactly one of them sends.

const TZ = "Europe/Athens";

function athensNow() {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hour12: false,
    }).formatToParts(new Date()).map((p) => [p.type, p.value]),
  );
  return { date: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour) % 24 };
}

async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

async function send(env, chatId, text) {
  // Telegram limit is 4096 chars; split on line boundaries.
  const chunks = [];
  let cur = "";
  for (const line of text.split("\n")) {
    if ((cur + line).length > 3800) { chunks.push(cur); cur = ""; }
    cur += line + "\n";
  }
  if (cur.trim()) chunks.push(cur);
  for (const c of chunks) {
    await tg(env, "sendMessage", {
      chat_id: chatId, text: c, parse_mode: "HTML", disable_web_page_preview: true,
    });
  }
}

async function loadReport(env) {
  const r = await fetch(`${env.DATA_URL}/report.json?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!r.ok) throw new Error(`report.json ${r.status}`);
  return r.json();
}

async function gameDayMessage(env, date) {
  const rep = await loadReport(env);
  const msg = (rep.messages || []).find((m) => m.date === date);
  if (!msg) return null;
  const ageH = (Date.now() - Date.parse(rep.generated)) / 3.6e6;
  const stale = ageH > 20
    ? `\n\n⚠️ Τα δεδομένα είναι ${Math.round(ageH)} ώρες παλιά — έλεγξε το GitHub Actions.`
    : "";
  return msg.text + stale;
}

export default {
  async scheduled(event, env, ctx) {
    const now = athensNow();
    if (now.hour !== 11) return;
    try {
      const text = await gameDayMessage(env, now.date);
      if (text) await send(env, env.TELEGRAM_CHAT_ID, text);
    } catch (e) {
      await send(env, env.TELEGRAM_CHAT_ID, `⚠️ Αποτυχία report: ${e.message}`);
    }
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/telegram" || request.method !== "POST") {
      return new Response("elf bot ok");
    }
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    const upd = await request.json();
    const m = upd.message;
    if (!m || !m.text) return new Response("ok");
    const chat = String(m.chat.id);
    const cmd = m.text.trim().split(/\s+/)[0].split("@")[0];

    // Anyone can learn their chat id (needed once for setup); everything else is owner-only.
    if (cmd === "/start" || cmd === "/id") {
      await send(env, chat, `Το chat ID σου: <code>${chat}</code>\nΒάλ' το στο secret TELEGRAM_CHAT_ID.`);
      return new Response("ok");
    }
    if (chat !== String(env.TELEGRAM_CHAT_ID)) return new Response("ok");

    try {
      if (cmd === "/report" || cmd === "/today") {
        const rep = await loadReport(env);
        const today = athensNow().date;
        const msgs = rep.messages || [];
        const msg = msgs.find((x) => x.date === today) || msgs.find((x) => x.date > today) || msgs[0];
        await send(env, chat, msg ? msg.text : "Δεν υπάρχει report ακόμα.");
      } else if (cmd === "/top") {
        const r = await fetch(`${env.DATA_URL}/predictions.json?t=${Date.now()}`);
        const p = await r.json();
        const rows = p.players.filter((x) => x.x_now != null).slice(0, 15)
          .map((x, i) => `${i + 1}. ${x.name} (${x.team}) ${x.position || ""} — <b>${x.x_now.toFixed(1)}</b>`
            + (x.price ? ` · ${x.price}cr` : ""));
        await send(env, chat, `📈 <b>Top xPIR — Αγωνιστική ${p.round}</b>\n` + rows.join("\n"));
      } else if (cmd === "/health") {
        const r = await fetch(`${env.DATA_URL}/predictions.json?t=${Date.now()}`);
        const p = await r.json();
        await send(env, chat, `Ενημέρωση: ${p.generated}\nFantasy: ${p.fantasy_ok ? "OK" : "ΟΧΙ"}\n`
          + ((p.health || []).join("\n") || "Χωρίς προβλήματα"));
      } else {
        await send(env, chat, "/report — report ημέρας\n/top — top xPIR\n/health — κατάσταση\n"
          + (env.DASHBOARD_URL ? `\n${env.DASHBOARD_URL}` : ""));
      }
    } catch (e) {
      await send(env, chat, `⚠️ ${e.message}`);
    }
    return new Response("ok");
  },
};
