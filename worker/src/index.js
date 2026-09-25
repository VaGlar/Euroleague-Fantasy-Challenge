// Cloudflare Worker: 11:00 (Athens) game-day notifications + Telegram bot commands.
//
// Secrets (wrangler secret put): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WEBHOOK_SECRET,
//   GH_DISPATCH_TOKEN (optional: fine-grained PAT, Actions read/write on this repo only)
// Vars: DATA_URL (base URL of data/public), DASHBOARD_URL, GH_REPO, GH_REF
//
// One hourly cron (xx:05 UTC); the handler works in Athens time (DST-proof):
//   10:05  game day -> start a fresh update that sends the report when done (~10:10)
//   11:05  fallback: send the report from the last data if the 10:05 one did not go out
//   first tip-off - 2h  -> pre-deadline check (lineup differs / trades pending)
// GitHub's own schedule runs hours late, so the timing lives here.

const TZ = "Europe/Athens";

function athensNow() {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hour12: false,
    }).formatToParts(new Date()).map((p) => [p.type, p.value]),
  );
  return { date: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour) % 24 };
}

const LINEUP_BUTTON = [[{ text: "👥 Πρόταση πεντάδας (/lineup)", callback_data: "lu:preview" }]];

async function getJson(env, name) {
  const r = await fetch(`${env.DATA_URL}/${name}?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!r.ok) throw new Error(`${name} ${r.status}`);
  return r.json();
}

async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

async function send(env, chatId, text, keyboard) {
  // Telegram limit is 4096 chars; split on line boundaries.
  const chunks = [];
  let cur = "";
  for (const line of text.split("\n")) {
    if ((cur + line).length > 3800) { chunks.push(cur); cur = ""; }
    cur += line + "\n";
  }
  if (cur.trim()) chunks.push(cur);
  for (const [i, c] of chunks.entries()) {
    const body = { chat_id: chatId, text: c, parse_mode: "HTML", disable_web_page_preview: true };
    if (keyboard && i === chunks.length - 1) body.reply_markup = { inline_keyboard: keyboard };
    await tg(env, "sendMessage", body);
  }
}

async function loadReport(env) {
  return getJson(env, "report.json");
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

async function dispatch(env, workflow, inputs) {
  return fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
      accept: "application/vnd.github+json",
      "user-agent": "elf-bot",
      "x-github-api-version": "2022-11-28",
    },
    body: JSON.stringify({ ref: env.GH_REF, inputs }),
  });
}

async function onCallback(env, cq) {
  const chat = String(cq.message?.chat?.id);
  await tg(env, "answerCallbackQuery", { callback_query_id: cq.id });
  if (chat !== String(env.TELEGRAM_CHAT_ID)) return;
  const [ns, action, nonce] = String(cq.data || "").split(":");
  if (ns !== "lu") return;
  if (action === "preview") {  // report button: keep it, it can be pressed again
    await startLineupPreview(env, chat);
    return;
  }
  // remove the buttons so a proposal can only be confirmed once
  await tg(env, "editMessageReplyMarkup", {
    chat_id: chat, message_id: cq.message.message_id, reply_markup: { inline_keyboard: [] },
  });
  if (action === "cancel") {
    await send(env, chat, "❌ Ακυρώθηκε — τίποτα δεν άλλαξε.");
  } else if (action === "apply" && /^[a-f0-9]{12}$/.test(nonce || "")) {
    const r = await dispatch(env, "lineup.yml", { mode: "apply", nonce });
    await send(env, chat, r.status === 204 ? "⏳ Εφαρμογή στο παιχνίδι… (~1 λεπτό)"
      : `⚠️ GitHub ${r.status}: ${(await r.text()).slice(0, 200)}`);
  }
}

async function startLineupPreview(env, chat) {
  if (!env.GH_DISPATCH_TOKEN) {
    await send(env, chat, "Λείπει το GH_DISPATCH_TOKEN — δες README.");
    return;
  }
  const r = await dispatch(env, "lineup.yml", { mode: "preview", nonce: "" });
  await send(env, chat, r.status === 204 ? "⏳ Διαβάζω την ομάδα σου και υπολογίζω… (~1 λεπτό)"
    : `⚠️ GitHub ${r.status}: ${(await r.text()).slice(0, 200)}`);
}

// Hourly: decide what (if anything) this hour is for. See the header comment.
async function hourly(env) {
  const now = athensNow();
  const rep = await loadReport(env);
  const gameDay = (rep.messages || []).some((m) => m.date === now.date);
  if (!gameDay) return;
  const canDispatch = Boolean(env.GH_DISPATCH_TOKEN);

  if (now.hour === 10 && canDispatch) {
    const r = await dispatch(env, "update.yml", { report: "true" });
    if (r.status !== 204) {
      await send(env, env.TELEGRAM_CHAT_ID,
        `⚠️ Το πρωινό update δεν ξεκίνησε (GitHub ${r.status}) — στις 11:00 έρχεται το report με τα τελευταία δεδομένα.`);
    }
  }
  if (now.hour === 11) {
    let sent = null;
    try { sent = await getJson(env, "sent.json"); } catch (e) { /* first run: no file yet */ }
    if (!sent || sent.date !== now.date) {
      const text = await gameDayMessage(env, now.date);
      if (text) {
        await send(env, env.TELEGRAM_CHAT_ID,
          text + "\n\n<i>(από τα τελευταία δεδομένα — το πρωινό update δεν ολοκληρώθηκε)</i>",
          LINEUP_BUTTON);
      }
    }
  }
  if (canDispatch) {
    const pred = await getJson(env, "predictions.json");
    const tu = (pred.turns || []).find((t) => t.date === now.date);
    const tipHour = tu ? Number(String(tu.first_tip).split(":")[0]) : NaN;
    if (now.hour === tipHour - 2) {
      await dispatch(env, "lineup.yml", { mode: "check", nonce: "" });
    }
  }
}

export default {
  async scheduled(event, env, ctx) {
    try {
      await hourly(env);
    } catch (e) {
      const h = athensNow().hour;
      if (h === 10 || h === 11) await send(env, env.TELEGRAM_CHAT_ID, `⚠️ Αποτυχία report: ${e.message}`);
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
    if (upd.callback_query) {
      await onCallback(env, upd.callback_query);
      return new Response("ok");
    }
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
        await send(env, chat, msg ? msg.text : "Δεν υπάρχει report ακόμα.", msg ? LINEUP_BUTTON : null);
      } else if (cmd === "/top") {
        const r = await fetch(`${env.DATA_URL}/predictions.json?t=${Date.now()}`);
        const p = await r.json();
        const rows = p.players.filter((x) => x.x_now != null).slice(0, 15)
          .map((x, i) => `${i + 1}. ${x.name} (${x.team}) ${x.position || ""} — <b>${x.x_now.toFixed(1)}</b>`
            + (x.price ? ` · ${x.price}cr` : ""));
        await send(env, chat, `📈 <b>Top xPTS — Αγωνιστική ${p.round}</b>\n` + rows.join("\n"));
      } else if (cmd === "/lineup") {
        await startLineupPreview(env, chat);
      } else if (cmd === "/update") {
        if (!env.GH_DISPATCH_TOKEN) {
          await send(env, chat, "Λείπει το GH_DISPATCH_TOKEN — δες README (Telegram /update).");
        } else {
          const r = await fetch(
            `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/update.yml/dispatches`, {
              method: "POST",
              headers: {
                authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
                accept: "application/vnd.github+json",
                "user-agent": "elf-bot",
                "x-github-api-version": "2022-11-28",
              },
              body: JSON.stringify({ ref: env.GH_REF, inputs: { notify: "true" } }),
            });
          await send(env, chat, r.status === 204
            ? "⏳ Το update ξεκίνησε (~2–4 λεπτά). Θα σου γράψω όταν τελειώσει."
            : `⚠️ GitHub ${r.status}: ${(await r.text()).slice(0, 200)}`);
        }
      } else if (cmd === "/health") {
        const r = await fetch(`${env.DATA_URL}/predictions.json?t=${Date.now()}`);
        const p = await r.json();
        await send(env, chat, `Ενημέρωση: ${p.generated}\nFantasy: ${p.fantasy_ok ? "OK" : "ΟΧΙ"}\n`
          + ((p.health || []).join("\n") || "Χωρίς προβλήματα"));
      } else {
        await send(env, chat, "/report — report ημέρας\n/top — top xPTS\n/lineup — πρόταση πεντάδας/αρχηγού με επιβεβαίωση\n/update — φρέσκα δεδομένα τώρα\n/health — κατάσταση\n"
          + (env.DASHBOARD_URL ? `\n${env.DASHBOARD_URL}` : ""));
      }
    } catch (e) {
      await send(env, chat, `⚠️ ${e.message}`);
    }
    return new Response("ok");
  },
};
