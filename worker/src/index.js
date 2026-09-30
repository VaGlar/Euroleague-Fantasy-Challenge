// Cloudflare Worker: schedule (07:00 update, 10:00 report, pre-deadline update + check, post-game update) + Telegram bot.
//
// Secrets (wrangler secret put): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WEBHOOK_SECRET,
//   GH_DISPATCH_TOKEN (optional: fine-grained PAT, Actions read/write on this repo only),
//   CF_ACCESS_CLIENT_ID + CF_ACCESS_CLIENT_SECRET (optional: service token for Cloudflare Access)
// Vars: DATA_URL (base URL of data/public), DASHBOARD_URL, GH_REPO, GH_REF
//
// One hourly cron (xx:05 UTC); the handler works in Athens time (DST-proof):
//   07:05  every day -> data update (both editions)
//   09:05  every day -> yesterday's Web Analytics report
//   10:05  game day -> the day's report on Telegram (from the 07:05 data)
//   first tip-off - 3h -> update: the day's late injury news reaches the advice before the deadline
//   first tip-off - 2h -> pre-deadline check (lineup differs / trades pending), on those fresh data
//   ~2.5h after the day's last tip-off -> update with the results
// GitHub's own schedule runs hours late, so all timing lives here.

const TZ = "Europe/Athens";

function athensNow() {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hour12: false,
    }).formatToParts(new Date()).map((p) => [p.type, p.value]),
  );
  return { date: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour) % 24 };
}

// Athens wall-clock time as a comparable number (ms), from the current time or a
// "YYYY-MM-DD" + "HH:MM" pair; only differences between such values are used.
function athensClock(date, hm) {
  if (date) {
    const [y, m, d] = date.split("-").map(Number), [H, M] = hm.split(":").map(Number);
    return Date.UTC(y, m - 1, d, H, M);
  }
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(new Date()).map((x) => [x.type, x.value]));
  return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute);
}
const RESULTS_DELAY_MIN = 150;   // last tip-off + 2h30 ≈ games over and box scores in

// Text inside an HTML-mode message: a stray "<" or "&" makes Telegram reject the whole message.
const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

const LINEUP_BUTTON = [[{ text: "👥 Πρόταση Starting five (/lineup)", callback_data: "lu:preview" }]];

// The personal site sits behind Cloudflare Access: the bot shows it a service token
// (secrets CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET). Without them nothing extra is sent.
function accessHeaders(env) {
  return env.CF_ACCESS_CLIENT_ID && env.CF_ACCESS_CLIENT_SECRET
    ? { "CF-Access-Client-Id": env.CF_ACCESS_CLIENT_ID, "CF-Access-Client-Secret": env.CF_ACCESS_CLIENT_SECRET }
    : {};
}

async function getJson(env, name) {
  const r = await fetch(`${env.DATA_URL}/${name}?t=${Date.now()}`,
    { headers: accessHeaders(env), redirect: "manual", cf: { cacheTtl: 0 } });
  // Access answers a missing/wrong token with a redirect to its login page (or 401/403)
  if ((r.status >= 300 && r.status < 400) || r.status === 401 || r.status === 403) {
    throw new Error(`${name}: Cloudflare Access ${r.status} — έλεγξε το service token (CF_ACCESS_CLIENT_ID/SECRET)`);
  }
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
  // Telegram limit is 4096 chars; split on line boundaries (inside a line only when that
  // line alone is too long, at a space where possible).
  const LIMIT = 3800;
  const pieces = (line) => {
    const out = [];
    while (line.length > LIMIT - 1) {
      let cut = line.lastIndexOf(" ", LIMIT - 1);
      if (cut <= 0) cut = LIMIT - 1;
      out.push(line.slice(0, cut));
      line = line.slice(cut).replace(/^ +/, "");
    }
    out.push(line);
    return out;
  };
  const chunks = [];
  let cur = "";
  for (const line of text.split("\n").flatMap(pieces)) {
    if (cur && (cur + line).length + 1 > LIMIT) { chunks.push(cur); cur = ""; }
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
      : `⚠️ GitHub ${r.status}: ${esc((await r.text()).slice(0, 200))}`);
  }
}

async function startLineupPreview(env, chat) {
  if (!env.GH_DISPATCH_TOKEN) {
    await send(env, chat, "Λείπει το GH_DISPATCH_TOKEN — δες README.");
    return;
  }
  const r = await dispatch(env, "lineup.yml", { mode: "preview", nonce: "" });
  await send(env, chat, r.status === 204 ? "⏳ Διαβάζω την ομάδα σου και υπολογίζω… (~1 λεπτό)"
    : `⚠️ GitHub ${r.status}: ${esc((await r.text()).slice(0, 200))}`);
}

// Hourly: decide what (if anything) this hour is for. See the header comment.
async function hourly(env) {
  const now = athensNow();
  const canDispatch = Boolean(env.GH_DISPATCH_TOKEN);
  const update = async (why) => {
    if (!canDispatch) return;
    const r = await dispatch(env, "update.yml", {});
    if (r.status !== 204) {
      await send(env, env.TELEGRAM_CHAT_ID, `⚠️ Το update (${why}) δεν ξεκίνησε: GitHub ${r.status} — έλεγξε το GH_DISPATCH_TOKEN.`);
    }
  };
  if (now.hour === 7) await update("07:00");
  if (now.hour === 9 && canDispatch) await dispatch(env, "analytics.yml", {});

  const rep = await loadReport(env);
  if (now.hour === 10 && (rep.messages || []).some((m) => m.date === now.date)) {
    const text = await gameDayMessage(env, now.date);
    if (text) await send(env, env.TELEGRAM_CHAT_ID, text, LINEUP_BUTTON);
  }

  const pred = await getJson(env, "predictions.json");
  const turns = pred.turns || [];
  const today = turns.find((t) => t.date === now.date);
  if (canDispatch && today) {
    const tipHour = Number(String(today.first_tip).split(":")[0]);
    // knowing who is out is worth far more than any model tweak (research/010), so refresh
    // injuries and news before the deadline; the 07:05 run already covers a 10:00 tip-off
    if (now.hour === tipHour - 3 && now.hour !== 7) await update("πριν τη λήξη");
    if (now.hour === tipHour - 2) await dispatch(env, "lineup.yml", { mode: "check", nonce: "" });
  }
  // results: one run in the hour after (last tip-off of a game day + RESULTS_DELAY_MIN)
  const nowC = athensClock();
  for (const t of turns) {
    const tips = (t.games || []).map((g) => String(g).split(" ").pop()).filter((x) => /^\d{1,2}:\d{2}$/.test(x));
    if (!tips.length) continue;
    const last = Math.max(...tips.map((hm) => athensClock(t.date, hm)));
    const since = (nowC - last) / 60000 - RESULTS_DELAY_MIN;
    if (since >= 0 && since < 60) { await update("μετά τους αγώνες"); break; }
  }
}

export default {
  async scheduled(event, env, ctx) {
    try {
      await hourly(env);
    } catch (e) {
      const h = athensNow().hour;
      if (h === 7 || h === 10) await send(env, env.TELEGRAM_CHAT_ID, `⚠️ Πρόβλημα στο πρόγραμμα του bot: ${esc(e.message)}`);
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
        const p = await getJson(env, "predictions.json");
        // the game's club codes (EFS, BAY, RMB…), not the API's (IST, MUN, MAD…)
        const clubs = await getJson(env, "clubs.json").catch(() => null);
        const tv = Object.fromEntries((Array.isArray(clubs) ? clubs : []).filter((c) => c.tv).map((c) => [c.code, c.tv]));
        const rows = p.players.filter((x) => x.x_now != null).slice(0, 15)
          .map((x, i) => `${i + 1}. ${esc(x.name)} (${esc(tv[x.team] || x.team)}) ${esc(x.position || "")} — <b>${x.x_now.toFixed(1)}</b>`
            + (x.price ? ` · ${x.price}cr` : ""));
        await send(env, chat, `📈 <b>Top xFPT — Round ${p.round}</b>\n` + rows.join("\n"));
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
            : `⚠️ GitHub ${r.status}: ${esc((await r.text()).slice(0, 200))}`);
        }
      } else if (cmd === "/health") {
        const p = await getJson(env, "predictions.json");
        await send(env, chat, `Ενημέρωση: ${p.generated}\nFantasy: ${p.fantasy_ok ? "OK" : "ΟΧΙ"}\n`
          + (esc((p.health || []).join("\n")) || "Χωρίς προβλήματα"));
      } else {
        await send(env, chat, "/report — report ημέρας\n/top — top xFPT\n/lineup — πρόταση Starting five/Captain με επιβεβαίωση\n/update — φρέσκα δεδομένα τώρα\n/health — κατάσταση\n"
          + (env.DASHBOARD_URL ? `\n${env.DASHBOARD_URL}` : ""));
      }
    } catch (e) {
      await send(env, chat, `⚠️ ${esc(e.message)}`);
    }
    return new Response("ok");
  },
};
