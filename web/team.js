// «Η ομάδα μου» for both editions.
//   public (HoopsLab): the team is entered by hand and lives on the device
//   personal: the team as it is in the game (P.my_team); trades come from the pipeline,
//     lineup and captain are applied with /lineup, so the screen is read-only
//   • setup on an empty court: tap a slot, pick a player of that position
//   • «Τι κάνω τώρα»: the moves between the saved team and the proposal (trades, lineup,
//     captain), each confirmed with ✓ once done in the game
//   • the lineup as a court; drag a player onto another to swap roles, tap for actions
// The team lives on the device (plus a backup link). Lineup, Turn plan and trades come
// from web/opt.js. Uses the page's helpers ($, esc, nm, f1, P, openPlayer, ...).
(function () {
  const KEY = "myteam_v1";
  const NEED = { Center: 2, Forward: 4, Guard: 4, "Head Coach": 1 };
  const LETTER = { Guard: "G", Forward: "F", Center: "C", "Head Coach": "HC" };
  const NAME = { Guard: "Guard", Forward: "Forward", Center: "Center", "Head Coach": "Coach" };
  const DAYS = ["Κυριακή", "Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο"];
  let mode = null;          // null | "setup"
  let setup = null;         // {players: [{id, price}]} while setting up
  let cache = { key: null, trs: null };

  // ------------------------------------------------------------ storage
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } };
  const GAME = () => P.edition !== "public";
  const save = (t) => { if (t.game) return; try { t.updated = new Date().toISOString(); localStorage.setItem(KEY, JSON.stringify(t)); } catch (e) {} };
  function encode(t) {
    const j = JSON.stringify({ p: t.players.map((x) => [x.id, x.price]), b: t.bank, r: t.roles || null, c: t.captain ?? null, u: t.used || null });
    return btoa(unescape(encodeURIComponent(j))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function decode(code) {
    const j = JSON.parse(decodeURIComponent(escape(atob(code.replace(/-/g, "+").replace(/_/g, "/")))));
    return { players: j.p.map(([id, price]) => ({ id, price })), bank: j.b, roles: j.r, captain: j.c, used: j.u || null, confirmed: true };
  }
  function importFromHash() {
    const m = location.hash.match(/[#&]t=([A-Za-z0-9_-]+)/);
    if (!m) return;
    try { save(decode(m[1])); toastSoon("Η ομάδα σου επανήλθε από τον σύνδεσμο"); }
    catch (e) { toastSoon("Ο σύνδεσμος ομάδας δεν είναι έγκυρος"); }
    history.replaceState(null, "", location.pathname + location.search);
  }

  // the personal team, as read from the game at the last update
  function gameTeam() {
    const my = P.my_team;
    if (!my || !(my.players || []).length) return null;
    const players = my.players.filter((r) => r.fantasy_id != null).map((r) => ({ id: Number(r.fantasy_id), price: r.price }));
    const real = (my.actual_lineup || []).filter((r) => r.role);
    const src = real.length === players.length ? real.map((r) => ({ id: Number(r.fantasy_id), role: r.role, captain: r.captain }))
      : (my.lineup || []).map((p) => ({ id: Number(p.id), role: p.role, captain: p.captain }));
    const roles = Object.fromEntries(src.map((x) => [x.id, x.role]));
    for (const x of players) if (!roles[x.id] && row(x.id)?.position === "Head Coach") roles[x.id] = "coach";
    return { game: true, fromGame: real.length === players.length, name: my.name, players, bank: Number(my.bank) || 0,
      roles, captain: src.find((x) => x.captain)?.id ?? null, confirmed: true };
  }

  // ------------------------------------------------------------ helpers
  const row = (id) => P.players.find((p) => p.fantasy_id === id);
  const key = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const sur = (n) => nm(n).replace(/^\S\. /, "");
  const started = () => P.players.some((p) => p.actual != null);
  const played = (r) => started() && r.actual != null;
  function rowsOf(t) {
    return t.players.map((x) => { const r = row(x.id); return r ? { ...r, id: x.id, price: x.price ?? r.price } : null; }).filter(Boolean);
  }
  function optRows(rows, t, inRound) {
    return rows.map((r) => ({ id: r.id, position: r.position, price: Number(r.price) || 0, x_h: r.x_h ?? 0,
      x_now: inRound && played(r) ? r.actual : (r.x_now ?? 0), turn: r.turn, played: inRound && played(r),
      cur_role: (t.roles || {})[r.id] || (r.position === "Head Coach" ? "coach" : "πάγκος"), cur_captain: t.captain === r.id }));
  }
  const fiveOk = (roles, rows) => {
    const five = rows.filter((r) => roles[r.id] === "5άδα");
    return five.length === 5 && ["Guard", "Forward", "Center"].every((pos) => five.some((r) => r.position === pos));
  };
  function deadline() {
    const t1 = (P.turns || [])[0];
    if (!t1) return "";
    const d = new Date(t1.date + "T00:00:00");
    const [h, m] = String(t1.first_tip).split(":").map(Number);
    const mins = h * 60 + m - 1;
    return `${DAYS[d.getDay()]} ${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
  }
  function toast(msg) {
    let t = document.getElementById("tmtoast");
    if (!t) { t = document.createElement("div"); t.id = "tmtoast"; t.className = "tm-toast"; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 2400);
  }
  function toastSoon(msg) { setTimeout(() => toast(msg), 900); }
  function sheet(html) { $("#sheet").innerHTML = html; $("#modal").classList.add("on"); document.body.classList.add("noscroll"); $("#sheet").scrollTop = 0; }

  // ------------------------------------------------------------ the plan: target and the steps to it
  function tradesFor(t, rows) {
    if (t.game) {
      const my = P.my_team || {};
      const pairs = (my.transfers || []).filter((m) => m.out_id != null && m.in_id != null)
        .map((m) => ({ out: { id: Number(m.out_id), price: m.price_out }, in: { id: Number(m.in_id), price: m.price_in } }))
        .sort((a, b) => (a.in.price - a.out.price) - (b.in.price - b.out.price));
      return { ti: { round: my.trade_round ?? P.round, max_trades: my.max_trades ?? 4 }, trs: { pairs, gain: my.transfer_gain ?? 0 } };
    }
    const ti = P.trade_info || { round: P.round, max_trades: 4, min_gain: 2 };
    const left = Math.max(0, ti.max_trades - usedTrades(t, ti));
    const k = t.players.map((x) => `${x.id}:${x.price}`).join(",") + "|" + t.bank + "|" + left + "|" + P.generated;
    if (cache.key !== k && !left) cache = { key: k, trs: { pairs: [], gain: 0 } };
    if (cache.key !== k) {
      const pool = P.players.filter((p) => p.fantasy_id != null && p.price != null)
        .map((p) => ({ id: p.fantasy_id, position: p.position, price: p.price, x_h: p.x_h ?? 0, x_now: p.x_now ?? 0 }));
      cache = { key: k, trs: ELFOPT.transfers(optRows(rows, t, false), pool, Number(t.bank) || 0,
        { maxTrades: left, minGain: ti.min_gain }) };
      // money-freeing trades first, so the bank never goes negative while making them
      cache.trs.pairs.sort((a, b) => (a.in.price - a.out.price) - (b.in.price - b.out.price));
    }
    return { ti, trs: cache.trs, left };
  }
  // trades already made for the round the proposal is for (so a done trade isn't re-proposed)
  const usedTrades = (t, ti) => (t.used && t.used.round === ti.round ? t.used.n : 0);
  function countTrade(t) {
    const ti = P.trade_info || { round: P.round };
    t.used = { round: ti.round, n: usedTrades(t, ti) + 1 };
  }
  // swaps turning `roles` into `target` (each keeps the five legal; in-round rules respected)
  function swapSteps(roles, target, rows, inRound) {
    const r = { ...roles }, steps = [];
    const byId = Object.fromEntries(rows.map((x) => [x.id, x]));
    const legal = (a, b) => {
      const ra = r[a], rb = r[b];
      if (inRound) {
        for (const [p, from, to] of [[byId[a], ra, rb], [byId[b], rb, ra]]) {
          if (!played(p)) continue;
          if (from === "πάγκος" && to !== "πάγκος") return false;
          if (from !== "πάγκος" && to !== "πάγκος") return false;
        }
      }
      return fiveOk({ ...r, [a]: rb, [b]: ra }, rows);
    };
    for (let guard = 0; guard < 12; guard++) {
      const a = rows.find((x) => x.position !== "Head Coach" && ["5άδα", "6ος"].includes(target[x.id]) && r[x.id] !== target[x.id]);
      if (!a) break;
      const want = target[a.id];
      const cands = rows.filter((x) => x.id !== a.id && r[x.id] === want && target[x.id] !== want);
      const b = cands.find((x) => target[x.id] === r[a.id] && legal(a.id, x.id)) || cands.find((x) => legal(a.id, x.id));
      if (!b) break;
      steps.push({ in: a, out: b, role: want });
      [r[a.id], r[b.id]] = [r[b.id], r[a.id]];
    }
    return steps;
  }
  function plan(t) {
    const rows = rowsOf(t);
    const inRound = started();
    const { ti, trs } = tradesFor(t, rows);
    const tradesNow = !inRound && ti.round === P.round;          // trades are for this round
    const pairs = trs.pairs;
    // squad after this round's trades (incoming players inherit the outgoing one's role)
    let after = t;
    if (tradesNow && pairs.length) {
      after = JSON.parse(JSON.stringify(t));
      for (const pr of pairs) applyTrade(after, pr.out.id, pr.in.id, pr.in.price);
    }
    const aRows = rowsOf(after);
    const res = ELFOPT.lineup(optRows(aRows, after, inRound), { inRound });
    let team = res ? res.team : [], turnPlan = [];
    if (res && !inRound) ({ team, plan: turnPlan } = ELFOPT.deferLaterTurns(res.team));
    const target = Object.fromEntries(team.map((p) => [p.id, p.role]));
    const targetCap = team.find((p) => p.captain)?.id ?? null;
    const items = [];
    if (tradesNow) for (const pr of pairs) {
      const o = rows.find((r) => r.id === pr.out.id), n = row(pr.in.id);
      items.push({ kind: "🔁", html: `Μεταγραφή: <b>${esc(sur(o.name))}</b> ➜ <b>${esc(sur(n.name))}</b>`,
        why: `${esc(n.team)}${n.turn ? " · T" + n.turn : ""} · ${f1(pr.out.price)} → ${f1(pr.in.price)} cr · +${f1((n.x_h ?? 0) - (o.x_h ?? 0))} xPTS3`,
        run: () => { applyTrade(t, pr.out.id, pr.in.id, pr.in.price); save(t); toast(`${sur(o.name)} ➜ ${sur(n.name)} · υπόλοιπο ${f1(t.bank)} cr`); } });
    }
    const pendingTrades = items.length > 0;
    const steps = pendingTrades ? swapSteps(after.roles || {}, target, aRows, inRound) : swapSteps(t.roles || {}, target, rows, inRound);
    // swaps that share a player are one move (a rotation of 3+ players reads as one line)
    const groups = [];
    for (const st of steps) {
      const g = groups.find((x) => x.some((y) => [y.in.id, y.out.id].some((id) => id === st.in.id || id === st.out.id)));
      if (g) g.push(st); else groups.push([st]);
    }
    const roles0 = { ...((pendingTrades ? after.roles : t.roles) || {}) };
    const ROLE_NAME = { "5άδα": "πεντάδα", "6ος": "6ος", "πάγκος": "πάγκος" }, ORDER = { "5άδα": 0, "6ος": 1, "πάγκος": 2 };
    for (const g of groups) {
      const waits = g.some((st) => !t.players.some((x) => x.id === st.in.id) || pendingTrades && !t.players.some((x) => x.id === st.out.id));
      const fin = { ...roles0 };
      for (const st of g) [fin[st.in.id], fin[st.out.id]] = [fin[st.out.id], fin[st.in.id]];
      const moved = [...new Set(g.flatMap((st) => [st.in, st.out]))].filter((r) => fin[r.id] !== roles0[r.id])
        .sort((x, y) => ORDER[fin[x.id]] - ORDER[fin[y.id]]);
      Object.assign(roles0, fin);
      const first = g[0], turn = first.in.turn ? " · T" + first.in.turn : "";
      const html = g.length === 1
        ? `${first.role === "5άδα" ? "Στην πεντάδα" : "Έκτος"}: <b>${esc(sur(first.in.name))}</b> <span class="muted">αντί ${esc(sur(first.out.name))}</span>`
        : `Αλλαγή θέσεων: ${moved.map((r) => `<b>${esc(sur(r.name))}</b> <span class="muted">→ ${ROLE_NAME[fin[r.id]]}</span>`).join(" · ")}`;
      items.push({ kind: "🔄", html,
        why: waits ? "μετά τη μεταγραφή" : t.game ? `με /lineup${turn}` : `σύρε ${g.length === 1 ? "τον" : "τους"} στο γήπεδο ή πάτα ✓${turn}`, wait: waits,
        run: () => { for (const st of g) if (!swap(t, st.in.id, st.out.id, true)) break; } });
    }
    if (targetCap != null && t.captain !== targetCap) {
      const c = aRows.find((r) => r.id === targetCap);
      const ready = t.players.some((x) => x.id === targetCap) && (t.roles || {})[targetCap] === "5άδα";
      items.push({ kind: "★", html: `Αρχηγός: <b>${esc(sur(c.name))}</b>`,
        why: ready ? `xPTS ${f1(inRound && played(c) ? c.actual : c.x_now)} · διπλοί πόντοι` : "μετά τη μεταγραφή και την πεντάδα", wait: !ready,
        run: () => { t.captain = targetCap; save(t); toast(`Αρχηγός: ${sur(c.name)}`); } });
    }
    return { rows, items, turnPlan, trs, ti, tradesNow, inRound, aRows, target, targetCap };
  }

  // ------------------------------------------------------------ actions on the saved team
  function applyTrade(t, outId, inId, price) {
    const i = t.players.findIndex((x) => x.id === outId);
    if (i < 0) return;
    const out = t.players[i];
    const outPrice = Number(out.price ?? row(outId)?.price) || 0;   // sold at the saved price
    t.players[i] = { id: inId, price };
    countTrade(t);
    t.bank = Math.round(((Number(t.bank) || 0) + outPrice - (Number(price) || 0)) * 10) / 10;
    t.roles = t.roles || {};
    t.roles[inId] = t.roles[outId]; delete t.roles[outId];
    if (t.captain === outId) t.captain = null;
  }
  function swap(t, a, b, quiet) {
    const rows = rowsOf(t), roles = t.roles || {};
    const ra = roles[a], rb = roles[b];
    if (!ra || !rb || ra === rb || ra === "coach" || rb === "coach") return false;
    const byId = Object.fromEntries(rows.map((x) => [x.id, x]));
    if (started()) {
      for (const [p, from, to] of [[byId[a], ra, rb], [byId[b], rb, ra]]) {
        if (!played(p)) continue;
        if (from === "πάγκος") { toast(`Ο ${sur(p.name)} έπαιξε από τον πάγκο — μένει εκεί`); return false; }
        if (to !== "πάγκος") { toast(`Ο ${sur(p.name)} έχει παίξει — μπορεί μόνο να βγει στον πάγκο`); return false; }
      }
    }
    const next = { ...roles, [a]: rb, [b]: ra };
    if (!fiveOk(next, rows)) {
      const five = rows.filter((r) => next[r.id] === "5άδα");
      const miss = ["Guard", "Forward", "Center"].filter((pos) => !five.some((r) => r.position === pos));
      toast(`Η πεντάδα χρειάζεται τουλάχιστον έναν ${miss.map((m) => NAME[m]).join(", ")}`);
      return false;
    }
    t.roles = next;
    if (t.captain && next[t.captain] !== "5άδα") { t.captain = null; toast("Ο αρχηγός βγήκε από την πεντάδα — διάλεξε νέο"); }
    else if (!quiet) toast(`${sur(byId[a].name)} ⇄ ${sur(byId[b].name)}`);
    save(t); render(); flash(a); flash(b);
    return true;
  }
  function flash(id) { requestAnimationFrame(() => document.querySelector(`#team .chip[data-fid="${id}"]`)?.classList.add("tm-flash")); }

  // ------------------------------------------------------------ court
  function chipHtml(r, t, extraCls = "") {
    const isPlayed = played(r);
    const cap = t && t.captain === r.id;
    return `<div class="chip${cap ? " cap" : ""} ${extraCls}" data-fid="${r.id}" tabindex="0" role="button" aria-label="${esc(nm(r.name))}">
      <div class="ct"><span>${LETTER[r.position] || ""}</span>${r.turn ? `<span class="tb t${r.turn > 1 ? 2 : 1}">T${r.turn}</span>` : ""}</div>
      <div class="cn">${esc(sur(r.name))}${inj(r) ? " 🚑" : ""}${r.price_trend === "up" ? " $" : ""}</div>
      <div class="cp${isPlayed ? " done" : ""}">${f1(isPlayed ? r.actual : r.x_now)}</div>
      <div class="cs">${r.opp ? `${r.home ? "🏠" : "✈️"} ${esc(r.opp)}` : ""}${r.price != null ? ` · ${f1(r.price)}` : ""}</div></div>`;
  }
  function courtHtml(t, rows, pl) {
    const moved = (r) => pl && !pl.tradesNow && pl.target[r.id] && (t.roles || {})[r.id] !== pl.target[r.id] ? "chg" : "";
    const by = (role) => rows.filter((r) => (t.roles || {})[r.id] === role || (role === "coach" && r.position === "Head Coach"));
    const five = by("5άδα");
    const line = (pos) => five.filter((r) => r.position === pos).map((r) => chipHtml(r, t, moved(r))).join("");
    return `<div class="tm-floor"><div class="court"><div class="crow">${line("Center")}</div><div class="crow">${line("Forward")}</div><div class="crow">${line("Guard")}</div></div>
      <div class="lanes"><div class="pair">
        <div class="lane"><h3>6ος · 100%</h3><div class="crow">${by("6ος").map((r) => chipHtml(r, t, moved(r))).join("")}</div></div>
        <div class="lane"><h3>Coach</h3><div class="crow">${by("coach").map((r) => chipHtml(r, t, moved(r))).join("")}</div></div></div>
        <div class="lane bench"><h3>Πάγκος · 50%</h3><div class="crow">${by("πάγκος").sort((a, b) => (b.x_now ?? 0) - (a.x_now ?? 0)).map((r) => chipHtml(r, t, moved(r))).join("")}</div></div></div></div>`;
  }

  // ------------------------------------------------------------ main screen
  function mainView(t, best) {
    const pl = plan(t);
    const rows = pl.rows;
    if (rows.length !== 11) {
      return `<div class="card warn"><h2>Κάποιοι παίκτες δεν βρέθηκαν (${rows.length}/11)</h2>
        <p>Μπορεί να άλλαξαν ομάδα ή να έφυγαν από τη λίστα του παιχνιδιού.</p><button class="linkbtn" id="tmEdit">Διόρθωση ομάδας</button></div>`;
    }
    const items = pl.items;
    const total = rows.reduce((a, r) => { const role = (t.roles || {})[r.id]; const v = played(r) ? r.actual : (r.x_now ?? 0);
      return a + v * (role === "πάγκος" ? 0.5 : 1) * (t.captain === r.id ? 2 : 1); }, 0);
    const head = pl.inRound
      ? `⏱ Αγωνιστική ${P.round} σε εξέλιξη`
      : `⏱ Αγωνιστική ${P.round} · κλείνει ${deadline()}`;
    const confirm = !t.confirmed ? `<li class="tm-item"><span class="tm-kind">👀</span><span class="tm-what"><b>Έλεγξε την πεντάδα σου</b>
        <span class="tm-why">Βάλαμε ρόλους με βάση την πρόταση. Αν στο παιχνίδι είναι αλλιώς, σύρε τους παίκτες όπως είναι εκεί.</span></span>
        <button class="tm-done" id="tmConfirm">✓ Είναι ίδια</button></li>` : "";
    const list = items.map((i, n) => `<li class="tm-item"><span class="tm-kind" aria-hidden="true">${i.kind}</span>
        <span class="tm-what">${i.html}<span class="tm-why">${i.why}</span></span>
        ${t.game ? "" : `<button class="tm-done" data-i="${n}" ${i.wait ? "disabled" : ""}>✓ Το έκανα</button>`}</li>`).join("");
    const turnPlan = pl.turnPlan.map((x) => { const s = pl.aRows.find((r) => r.id === x.start.id), b = pl.aRows.find((r) => r.id === x.bench.id);
      return `<li>🕐 <b>Πριν το T${x.bench.turn}</b>: αν ο ${esc(sur(s.name))} φέρει κάτω από ${Math.round(x.bench.x_now)}, βάλε τον ${esc(sur(b.name))}.</li>`; }).join("");
    const nextTrades = !pl.tradesNow && pl.trs.pairs.length ? `<div class="card"><h2>Μεταγραφές για την αγωνιστική ${pl.ti.round}
        <small class="muted">(${pl.ti.max_trades > 4 ? "απεριόριστες" : `έως ${pl.ti.max_trades}`}${usedTrades(t, pl.ti) ? ` · έκανες ${usedTrades(t, pl.ti)}` : ""} · γίνονται όταν τελειώσει η τρέχουσα)</small></h2>
        <ul class="tm-list">${pl.trs.pairs.map((pr, n) => { const o = rows.find((r) => r.id === pr.out.id), nn = row(pr.in.id);
          return `<li class="tm-item"><span class="tm-kind">🔁</span><span class="tm-what"><b>${esc(sur(o.name))}</b> ➜ <b>${esc(sur(nn.name))}</b>
            <span class="tm-why">${esc(nn.team)} · ${f1(pr.out.price)} → ${f1(pr.in.price)} cr · +${f1((nn.x_h ?? 0) - (o.x_h ?? 0))} xPTS3</span></span>
            ${t.game ? "" : `<button class="tm-done" data-n="${n}">✓ Το έκανα</button>`}</li>`; }).join("")}</ul></div>` : "";
    const done = !items.length && t.confirmed;
    const upd = P.generated ? new Date(P.generated).toLocaleString("el-GR", { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "";
    const hint = t.game
      ? `Πεντάδα και αρχηγός εφαρμόζονται με <b>/lineup</b> στο Telegram· τις μεταγραφές τις κάνεις στο παιχνίδι. Η ομάδα διαβάστηκε από το παιχνίδι ${esc(upd)}.`
      : "Κάνε τις αλλαγές στο παιχνίδι και πάτα ✓ — η ομάδα σου εδώ ενημερώνεται μόνη της.";
    return `<header class="tm-top"><div><h2 class="tm-h">${t.game ? esc(t.name || "Η ομάδα μου") : "Η ομάδα μου"}</h2>
        <div class="muted">Υπόλοιπο <b>${f1(t.bank)} cr</b> · αναμενόμενοι πόντοι <b>${f1(total)}</b></div>
        <div class="tm-dead">${head}</div></div>
        ${t.game ? "" : `<div class="tm-morewrap"><button class="tm-more" id="tmMore" aria-label="Περισσότερα">⋯</button><div id="tmMenu"></div></div>`}</header>
      <div class="card"><h2>Τι κάνω τώρα <small class="muted">${items.length ? `${items.length} ${items.length === 1 ? "βήμα" : "βήματα"}` : ""}</small></h2>
        ${done ? `<div class="tm-ready">✅ Έτοιμος για την αγωνιστική</div>` : `<ul class="tm-list">${confirm}${list}</ul>`}
        ${turnPlan ? `<ul class="plan">${turnPlan}</ul>` : ""}
        <p class="tm-hint">${hint}
        ${pl.inRound ? "Μέσα στην αγωνιστική: όποιος έπαιξε μπορεί μόνο να βγει στον πάγκο· το x2 μόνο σε παίκτη που δεν έχει παίξει." : ""}</p></div>
      ${nextTrades}
      <div class="card tm-courtcard"><h2>${t.game ? (t.fromGame ? "Στο παιχνίδι τώρα" : "Η πρόταση") : "Η πεντάδα σου"} <small class="muted">${t.game ? (t.fromGame ? "διακεκομμένο = αλλάζει με την πρόταση" : "δεν διαβάστηκε η πεντάδα του παιχνιδιού") : "σύρε έναν παίκτη πάνω σε άλλον για αλλαγή θέσης"}</small></h2>
        ${courtHtml(t, rows, t.game ? pl : null)}<p class="tm-hint">${t.game ? "Πάτα έναν παίκτη για στατιστικά και επόμενα παιχνίδια." : "Πάτα έναν παίκτη για αρχηγό, αντικατάσταση ή στατιστικά."}</p></div>
      ${bestCard(best)}`;
  }

  // ------------------------------------------------------------ player actions
  function playerSheet(t, id) {
    const rows = rowsOf(t), r = rows.find((x) => x.id === id);
    if (!r) return;
    const role = r.position === "Head Coach" ? "coach" : (t.roles || {})[id];
    const canCap = role === "5άδα" && t.captain !== id && !(played(r) && t.captain !== id);
    const capWhy = role !== "5άδα" ? "μόνο παίκτης της πεντάδας" : t.captain === id ? "είναι ήδη αρχηγός" : played(r) ? "έχει ήδη παίξει" : "διπλοί πόντοι";
    sheet(`<div class="sh"><div><h2>${esc(nm(r.name))}</h2>
        <div class="muted">${esc(r.team)} · ${NAME[r.position]} · ${f1(r.price)} cr${r.turn ? ` · Turn ${r.turn}` : ""}${role && role !== "coach" ? ` · ${role}` : ""}</div></div>
        <button class="x" aria-label="Κλείσιμο" onclick="closePlayer()">×</button></div>
      <div class="kpis"><div class="kpi"><b>${f1(played(r) ? r.actual : r.x_now)}</b><span>${played(r) ? "πόντοι" : "xPTS"}</span></div>
        <div class="kpi"><b>${f1(r.x_h)}</b><span>xPTS3</span></div><div class="kpi"><b>${r.value == null ? "–" : r.value.toFixed(2)}</b><span>xPTS3/cr</span></div></div>
      <div class="tm-acts">
        ${r.position !== "Head Coach" ? `<button class="tm-act" id="aCap" ${canCap ? "" : "disabled"}><span>★</span><div>Κάν' τον αρχηγό<small>${capWhy}</small></div></button>
        <button class="tm-act" id="aSwap"><span>⇄</span><div>Αλλαγή θέσης με…<small>ή σύρε τον πάνω σε άλλον παίκτη</small></div></button>` : ""}
        <button class="tm-act" id="aRep"><span>🔁</span><div>Αντικατάσταση (μεταγραφή)<small>${NAME[r.position]} έως ${f1((Number(t.bank) || 0) + Number(r.price || 0))} cr</small></div></button>
        <button class="tm-act" id="aPrice"><span>✎</span><div>Διόρθωση τιμής<small>αν στο παιχνίδι σου διαφέρει (τώρα ${f1(r.price)} cr)</small></div></button>
        <button class="tm-act" id="aInfo"><span>📊</span><div>Στατιστικά και επόμενα παιχνίδια<small>η πλήρης καρτέλα του παίκτη</small></div></button>
      </div>`);
    const on = (i, fn) => { const el = document.getElementById(i); if (el) el.onclick = fn; };
    on("aCap", () => { t.captain = id; save(t); closePlayer(); render(); flash(id); toast(`Αρχηγός: ${sur(r.name)}`); });
    on("aSwap", () => {
      const others = rows.filter((x) => x.id !== id && x.position !== "Head Coach" && (t.roles || {})[x.id] !== role);
      sheet(`<div class="sh"><div><h2>${esc(sur(r.name))} ⇄ …</h2><div class="muted">Τώρα: ${role}</div></div>
          <button class="x" aria-label="Κλείσιμο" onclick="closePlayer()">×</button></div>
        <div class="tm-acts">${others.map((x) => `<button class="tm-act" data-q="${x.id}"><span>${LETTER[x.position]}</span><div>${esc(nm(x.name))}
          <small>${(t.roles || {})[x.id]} · ${played(x) ? `έφερε ${f1(x.actual)}` : `xPTS ${f1(x.x_now)}`}</small></div></button>`).join("")}</div>`);
      document.querySelectorAll("#sheet [data-q]").forEach((b) => b.onclick = () => { if (swap(t, id, Number(b.dataset.q))) closePlayer(); });
    });
    on("aRep", () => replaceSheet(t, r));
    on("aPrice", () => {
      sheet(`<div class="sh"><div><h2>Τιμή: ${esc(sur(r.name))}</h2><div class="muted">Όπως φαίνεται στο παιχνίδι σου</div></div>
          <button class="x" aria-label="Κλείσιμο" onclick="closePlayer()">×</button></div>
        <input id="tmPrice" class="tm-input" inputmode="decimal" value="${f1(r.price)}" autocomplete="off">
        <button class="tm-primary" id="tmPriceOk">Αποθήκευση</button>`);
      $("#tmPriceOk").onclick = () => {
        const v = parseFloat(String($("#tmPrice").value).replace(",", "."));
        if (isNaN(v) || v <= 0) { toast("Γράψε μια τιμή, π.χ. 7,5"); return; }
        t.players.find((x) => x.id === id).price = v; save(t); closePlayer(); render(); toast(`${sur(r.name)}: ${f1(v)} cr`);
      };
    });
    on("aInfo", () => openPlayer(r.person_id));
  }
  function replaceSheet(t, r) {
    const max = (Number(t.bank) || 0) + Number(r.price || 0);
    const have = new Set(t.players.map((x) => x.id));
    const list = P.players.filter((p) => p.position === r.position && p.fantasy_id != null && p.price != null && !have.has(p.fantasy_id))
      .sort((a, b) => (b.x_h ?? 0) - (a.x_h ?? 0));
    const draw = (q) => {
      const k = key(q).trim();
      $("#tmList").innerHTML = list.filter((p) => !k || key(p.name).includes(k)).slice(0, 40).map((p) => `<button class="tm-pick" data-n="${p.fantasy_id}" ${p.price > max ? "disabled" : ""}>
          <span><b>${esc(nm(p.name))}</b></span><span class="tm-pv"><b>${f1(p.x_h)}</b><small>xPTS3</small></span>
          <span class="muted tm-pm">${esc(p.team)} · ${f1(p.price)} cr${p.price > max ? " · δεν φτάνει το υπόλοιπο" : ""}</span></button>`).join("") || `<p class="muted">Κανένας ${NAME[r.position]} με αυτό το όνομα.</p>`;
      document.querySelectorAll("#tmList [data-n]").forEach((b) => b.onclick = () => {
        const n = row(Number(b.dataset.n));
        applyTrade(t, r.id, n.fantasy_id, n.price); save(t); closePlayer(); render(); flash(n.fantasy_id);
        toast(`${sur(r.name)} ➜ ${sur(n.name)} · υπόλοιπο ${f1(t.bank)} cr`);
      });
    };
    sheet(`<div class="sh"><div><h2>Αντικατάσταση: ${esc(sur(r.name))}</h2><div class="muted">${NAME[r.position]} · έως ${f1(max)} cr · οι καλύτεροι σε xPTS3 πρώτα</div></div>
        <button class="x" aria-label="Κλείσιμο" onclick="closePlayer()">×</button></div>
      <input id="tmQ" class="tm-input" placeholder="Αναζήτηση ${NAME[r.position]}…" autocomplete="off"><div id="tmList"></div>`);
    draw(""); $("#tmQ").addEventListener("input", (e) => draw(e.target.value));
  }

  // ------------------------------------------------------------ drag to swap (pointer events: touch + mouse)
  function bindCourt(t) {
    document.querySelectorAll("#team .chip[data-fid]").forEach((el) => {
      const id = Number(el.dataset.fid);
      const r = row(id);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); playerSheet(t, id); } });
      el.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        const sx = e.clientX, sy = e.clientY;
        let ghost = null, target = null, last = null, raf = 0;
        try { el.setPointerCapture(e.pointerId); } catch (err) {}
        const hover = (x, y) => {
          const under = document.elementFromPoint(x, y)?.closest("#team .chip[data-fid]");
          const tid = under ? Number(under.dataset.fid) : null;
          if (target && target !== under) target.classList.remove("tm-target");
          target = under && tid !== id && row(tid)?.position !== "Head Coach" && (t.roles || {})[tid] !== (t.roles || {})[id] ? under : null;
          if (target) target.classList.add("tm-target");
        };
        // near the top/bottom edge the page scrolls, so the bench is reachable on a phone
        const edge = () => {
          if (!ghost || !last) { raf = 0; return; }
          const zone = 70, h = window.innerHeight;
          const dy = last.y > h - zone ? Math.ceil((last.y - (h - zone)) / 5) : last.y < zone ? -Math.ceil((zone - last.y) / 5) : 0;
          if (dy) { window.scrollBy(0, dy); hover(last.x, last.y); }
          raf = requestAnimationFrame(edge);
        };
        const move = (ev) => {
          if (!ghost && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 8) return;
          if (!r || r.position === "Head Coach") return;
          if (!ghost) { document.getElementById("tmtoast")?.classList.remove("on"); ghost = el.cloneNode(true); ghost.classList.add("tm-ghost"); document.body.appendChild(ghost); el.classList.add("tm-lift"); }
          ghost.style.left = ev.clientX + "px"; ghost.style.top = ev.clientY + "px";
          last = { x: ev.clientX, y: ev.clientY };
          hover(last.x, last.y);
          if (!raf) raf = requestAnimationFrame(edge);
        };
        const up = () => {
          el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up);
          if (raf) cancelAnimationFrame(raf);
          if (!ghost) { playerSheet(t, id); return; }          // a tap, not a drag
          ghost.remove(); ghost = null; el.classList.remove("tm-lift");
          if (target) { target.classList.remove("tm-target"); swap(t, id, Number(target.dataset.fid)); }
        };
        el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
      });
    });
  }

  // ------------------------------------------------------------ menu
  function menu(t, best) {
    const host = $("#tmMenu");
    if (host.innerHTML) { host.innerHTML = ""; return; }
    host.innerHTML = `<div class="tm-menu" role="menu">
      <button id="mBackup">🔗 Αντίγραφο ασφαλείας (σύνδεσμος)</button>
      <button id="mEdit">✏️ Αλλαγή ομάδας</button>
      <button id="mBank">💰 Διόρθωση υπολοίπου</button>
      ${usedTrades(t, P.trade_info || {}) ? `<button id="mUsed">🔁 Μηδένισε τις μεταγραφές που έκανες (${usedTrades(t, P.trade_info || {})})</button>` : ""}
      <button id="mInstall">📱 Βάλ' το στην οθόνη σου</button>
      <button id="mMail">✉️ Ιδέα ή πρόβλημα; Αντιγραφή του email μας</button>
      <button id="mDel" class="tm-danger">🗑 Διαγραφή ομάδας</button></div>`;
    $("#mBackup").onclick = async () => {
      host.innerHTML = "";
      const link = location.origin + location.pathname + "#t=" + encode(t);
      try { await navigator.clipboard.writeText(link); toast("Ο σύνδεσμος αντιγράφηκε — κράτα τον π.χ. στις σημειώσεις"); }
      catch (e) { sheet(`<div class="sh"><h2>Σύνδεσμος ομάδας</h2><button class="x" onclick="closePlayer()">×</button></div>
        <p class="muted">Αντίγραψε και κράτα τον. Ανοίγοντάς τον σε άλλη συσκευή επανέρχεται η ομάδα σου.</p>
        <textarea class="tm-input" rows="4" readonly onclick="this.select()">${esc(link)}</textarea>`); }
    };
    $("#mEdit").onclick = () => { host.innerHTML = ""; setup = { players: t.players.map((x) => ({ ...x })) }; mode = "setup"; render(best); };
    $("#mBank").onclick = () => {
      host.innerHTML = "";
      sheet(`<div class="sh"><div><h2>Υπόλοιπο</h2><div class="muted">Όπως φαίνεται στο παιχνίδι σου (credits)</div></div>
          <button class="x" onclick="closePlayer()">×</button></div>
        <input id="tmBank" class="tm-input" inputmode="decimal" value="${f1(t.bank)}" autocomplete="off"><button class="tm-primary" id="tmBankOk">Αποθήκευση</button>`);
      $("#tmBankOk").onclick = () => { const v = parseFloat(String($("#tmBank").value).replace(",", "."));
        if (isNaN(v) || v < 0) { toast("Γράψε ένα ποσό, π.χ. 3,5"); return; }
        t.bank = v; save(t); closePlayer(); render(best); };
    };
    if ($("#mUsed")) $("#mUsed").onclick = () => { host.innerHTML = ""; t.used = null; save(t); render(best); toast("Μηδενίστηκαν"); };
    $("#mMail").onclick = async () => { host.innerHTML = "";
      toast(await copyText(FEEDBACK_MAIL) ? `Αντιγράφηκε: ${FEEDBACK_MAIL}` : FEEDBACK_MAIL); };
    $("#mInstall").onclick = () => { host.innerHTML = ""; installGuide(true); };
    $("#mDel").onclick = () => {
      host.innerHTML = "";
      sheet(`<div class="sh"><h2>Διαγραφή της ομάδας από αυτή τη συσκευή;</h2><button class="x" onclick="closePlayer()">×</button></div>
        <p class="muted">Αν έχεις κρατήσει σύνδεσμο αντιγράφου, μπορείς να την επαναφέρεις αργότερα.</p>
        <button class="tm-primary tm-danger-bg" id="tmDelOk">Διαγραφή</button>`);
      $("#tmDelOk").onclick = () => { try { localStorage.removeItem(KEY); } catch (e) {} closePlayer(); setup = null; mode = null; render(best); };
    };
  }
  document.addEventListener("click", (e) => { if (!e.target.closest("#tmMenu, #tmMore")) { const h = document.getElementById("tmMenu"); if (h) h.innerHTML = ""; } });

  // ------------------------------------------------------------ setup on an empty court
  function setupView() {
    const ps = setup.players.map((x) => ({ ...x, r: row(x.id) })).filter((x) => x.r);
    const have = (pos) => ps.filter((x) => x.r.position === pos);
    const spent = ps.reduce((a, x) => a + (Number(x.price) || 0), 0);
    const full = Object.entries(NEED).every(([pos, n]) => have(pos).length === n);
    const slots = (pos) => have(pos).map((x) => `<div class="chip tm-setchip" data-rm="${x.id}" role="button" tabindex="0" title="πάτα για αφαίρεση">
        <div class="ct"><span>${LETTER[pos]}</span><span>✕</span></div><div class="cn">${esc(sur(x.r.name))}</div>
        <div class="cs">${esc(x.r.team)} · ${f1(x.price)}</div></div>`).join("")
      + Array.from({ length: NEED[pos] - have(pos).length }, () => `<button class="tm-slot" data-pos="${pos}"><b>+</b>${NAME[pos]}</button>`).join("");
    const had = !!load();
    return `<header class="tm-top"><div><h2 class="tm-h">${had ? "Αλλαγή ομάδας" : "Φτιάξε την ομάδα σου"}</h2>
        <div class="muted">Πάτα μια κενή θέση και διάλεξε παίκτη · ${ps.length}/11</div></div></header>
      <div class="card tm-courtcard"><div class="tm-floor"><div class="court"><div class="crow">${slots("Center")}</div></div>
        <div class="lanes">
          <div class="lane"><h3>Forwards · ${have("Forward").length}/4</h3><div class="crow">${slots("Forward")}</div></div>
          <div class="lane"><h3>Guards · ${have("Guard").length}/4</h3><div class="crow">${slots("Guard")}</div></div>
          <div class="lane"><h3>Coach · ${have("Head Coach").length}/1</h3><div class="crow">${slots("Head Coach")}</div></div></div></div>
        <div class="tm-money"><span>Κόστος ομάδας <b>${f1(spent)}</b> cr</span><span>Υπόλοιπο <b>${f1(Math.max(0, 100 - spent))}</b> cr</span></div>
        <button class="tm-primary" id="tmFinish" ${full ? "" : "disabled"}>${full ? "Αποθήκευση ➜" : `Λείπουν ${11 - ps.length}`}</button>
        ${had ? '<button class="linkbtn" id="tmCancel" style="display:block;margin:6px auto 0">Άκυρο</button>' : ""}
        <p class="tm-hint">Οι τιμές συμπληρώνονται με τις σημερινές· αν διαφέρουν στο παιχνίδι σου, τις διορθώνεις μετά από την καρτέλα του παίκτη. Το υπόλοιπο το διορθώνεις από το ⋯.</p></div>`;
  }
  function pickSheet(pos, best) {
    const have = new Set(setup.players.map((x) => x.id));
    const list = P.players.filter((p) => p.position === pos && p.fantasy_id != null && p.price != null && !have.has(p.fantasy_id))
      .sort((a, b) => (b.price ?? 0) - (a.price ?? 0));
    const draw = (q) => {
      const k = key(q).trim();
      $("#tmList").innerHTML = list.filter((p) => !k || key(p.name).includes(k)).slice(0, 60).map((p) => `<button class="tm-pick" data-p="${p.fantasy_id}">
          <span><b>${esc(nm(p.name))}</b></span><span class="tm-pv"><b>${f1(p.price)}</b><small>cr</small></span>
          <span class="muted tm-pm">${esc(p.team)} · xPTS ${f1(p.x_now)}</span></button>`).join("") || `<p class="muted">Κανένας ${NAME[pos]} με αυτό το όνομα.</p>`;
      document.querySelectorAll("#tmList [data-p]").forEach((b) => b.onclick = () => {
        const r = row(Number(b.dataset.p)); setup.players.push({ id: r.fantasy_id, price: r.price }); closePlayer(); render(best);
      });
    };
    sheet(`<div class="sh"><div><h2>Διάλεξε ${NAME[pos]}</h2><div class="muted">Γράψε μερικά γράμματα του ονόματος</div></div>
        <button class="x" aria-label="Κλείσιμο" onclick="closePlayer()">×</button></div>
      <input id="tmQ" class="tm-input" placeholder="Αναζήτηση ${NAME[pos]}…" autocomplete="off"><div id="tmList"></div>`);
    draw(""); setTimeout(() => $("#tmQ")?.focus(), 50); $("#tmQ").addEventListener("input", (e) => draw(e.target.value));
  }
  function finishSetup() {
    const old = load();
    const ids = new Set(setup.players.map((x) => x.id));
    const spent = setup.players.reduce((a, x) => a + (Number(x.price) || 0), 0);
    let t = { players: setup.players, bank: old ? old.bank : Math.round(Math.max(0, 100 - spent) * 10) / 10,
      roles: null, captain: null, confirmed: false };
    if (old && old.roles) {   // keep known roles for players that stayed; newcomers inherit a free role
      const kept = Object.fromEntries(Object.entries(old.roles).filter(([id]) => ids.has(Number(id))));
      if (Object.keys(kept).length === 11) { t.roles = kept; t.captain = ids.has(old.captain) ? old.captain : null; t.confirmed = old.confirmed; }
    }
    if (!t.roles) {           // start from the proposal; the user confirms or drags to match the game
      const rows = rowsOf(t);
      const res = ELFOPT.lineup(optRows(rows, t, false));
      t.roles = Object.fromEntries(res.team.map((p) => [p.id, p.role]));
      t.captain = res.team.find((p) => p.captain)?.id ?? null;
    }
    save(t); setup = null; mode = null;
  }

  // ------------------------------------------------------------ render
  function bestCard(best) {
    if (!best) return "";
    return `<details class="card"><summary><b>Βέλτιστη ομάδα από το μηδέν</b> <span class="muted">· ${f1(best.cost)} cr</span></summary>
      <p class="muted">Με απεριόριστες αλλαγές (π.χ. μετά τις αγωνιστικές 6, 13, 18…).</p>
      ${courtView(best.team.map((p) => ({ ...p, actual: null })), null)}</details>`;
  }
  function render(best) {
    best = best === undefined ? P.best_team : best;
    if (GAME()) {
      const g = gameTeam();
      if (!g) { $("#team").innerHTML = `<div class="card warn"><h2>Η ομάδα δεν είναι διαθέσιμη</h2>
        <p>Χρειάζεται έγκυρο <code>FANTASY_TOKEN</code> στα GitHub Secrets.</p></div>${bestCard(best)}`; return; }
      $("#team").innerHTML = mainView(g, best);
      document.querySelectorAll("#team .chip[data-fid]").forEach((el) => el.onclick = () => { const r = row(Number(el.dataset.fid)); if (r) openPlayer(r.person_id); });
      return;
    }
    const t = load();
    if (mode === "setup" || !t) {
      if (!setup) setup = { players: [] };
      mode = "setup";
      $("#team").innerHTML = setupView();
      document.querySelectorAll("#team .tm-slot").forEach((b) => b.onclick = () => pickSheet(b.dataset.pos, best));
      document.querySelectorAll("#team [data-rm]").forEach((c) => c.onclick = () => {
        setup.players = setup.players.filter((x) => x.id !== Number(c.dataset.rm)); render(best);
      });
      const fin = document.getElementById("tmFinish");
      if (fin) fin.onclick = () => { finishSetup(); render(best); window.scrollTo({ top: 0 }); toast("Η ομάδα αποθηκεύτηκε"); };
      const cancel = document.getElementById("tmCancel");
      if (cancel) cancel.onclick = () => { setup = null; mode = null; render(best); };
      return;
    }
    if (!t.roles || Object.keys(t.roles).length !== t.players.length) {   // e.g. an old backup link: start from the proposal
      const res = ELFOPT.lineup(optRows(rowsOf(t), t, false));
      if (res) { t.roles = Object.fromEntries(res.team.map((p) => [p.id, p.role])); t.captain = res.team.find((p) => p.captain)?.id ?? null; t.confirmed = false; save(t); }
    }
    const pl = mainView(t, best);
    $("#team").innerHTML = pl;
    const p = plan(t);   // cached trades: cheap
    document.querySelectorAll("#team .tm-done[data-i]").forEach((b) => b.onclick = () => {
      const it = p.items[Number(b.dataset.i)]; if (!it) return;
      it.run(); render(best);
    });
    document.querySelectorAll("#team .tm-done[data-n]").forEach((b) => b.onclick = () => {
      const pr = p.trs.pairs[Number(b.dataset.n)];
      applyTrade(t, pr.out.id, pr.in.id, pr.in.price); save(t); render(best); toast(`Έγινε · υπόλοιπο ${f1(t.bank)} cr`);
    });
    const on = (i, fn) => { const el = document.getElementById(i); if (el) el.onclick = fn; };
    on("tmConfirm", () => { t.confirmed = true; save(t); render(best); });
    on("tmMore", (e) => { e.stopPropagation(); menu(t, best); });
    on("tmEdit", () => { setup = { players: t.players.map((x) => ({ ...x })) }; mode = "setup"; render(best); });
    bindCourt(t);
  }

  // styles for this screen
  const css = document.createElement("style");
  css.textContent = `
  .tm-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin: 2px 0 12px; }
  .tm-h { font-size: 20px; margin: 0; }
  .tm-dead { display: inline-block; font-size: 12px; font-weight: 600; color: var(--accent); margin-top: 4px;
    background: color-mix(in srgb, var(--accent) 12%, transparent); border-radius: 999px; padding: 2px 9px; }
  .tm-morewrap { position: relative; }
  .tm-more { border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary); border-radius: 50%;
    width: 38px; height: 38px; font-size: 18px; cursor: pointer; }
  .tm-menu { position: absolute; right: 0; top: 44px; z-index: 5; background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 12px; box-shadow: 0 6px 20px rgba(0,0,0,.15); min-width: 230px; overflow: hidden; }
  .tm-menu button, .tm-menu a { box-sizing: border-box; text-decoration: none; }
  .tm-menu button, .tm-menu a { display: block; width: 100%; text-align: left; border: 0; background: none; color: var(--text-primary);
    font: inherit; padding: 12px 14px; cursor: pointer; }
  .tm-menu button + button, .tm-menu button + a, .tm-menu a + button { border-top: 1px solid var(--border); }
  .tm-danger { color: var(--critical) !important; }
  .tm-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
  .tm-item { display: grid; grid-template-columns: 30px 1fr auto; gap: 10px; align-items: center; border: 1px solid var(--border);
    border-radius: 12px; padding: 10px; background: var(--surface-0); }
  .tm-kind { width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; background: var(--surface-1);
    border: 1px solid var(--border); }
  .tm-why { display: block; color: var(--text-muted); font-size: 12px; margin-top: 1px; }
  .tm-done { border: 0; border-radius: 10px; padding: 8px 12px; background: var(--text-primary); color: var(--surface-1);
    font: inherit; font-weight: 600; font-size: 13px; cursor: pointer; white-space: nowrap; }
  .tm-done:disabled { opacity: .35; cursor: default; }
  .tm-ready { padding: 12px; border-radius: 12px; font-weight: 600; background: color-mix(in srgb, var(--good) 14%, transparent); }
  .tm-hint { color: var(--text-muted); font-size: 12px; margin: 8px 2px 0; }
  .tm-acts { display: grid; gap: 8px; margin-top: 12px; }
  .tm-act { display: flex; gap: 10px; align-items: center; width: 100%; text-align: left; border: 1px solid var(--border);
    background: var(--surface-1); color: var(--text-primary); border-radius: 12px; padding: 12px; cursor: pointer; font: inherit; }
  .tm-act > span { width: 24px; text-align: center; font-size: 17px; }
  .tm-act small { display: block; color: var(--text-muted); font-size: 12px; }
  .tm-act:disabled { opacity: .45; cursor: default; }
  /* the whole squad stands on the court: the five in the half with the basket, 6th/coach/bench past the half-court line */
  .tm-floor { position: relative; background: var(--court); border: 2px solid var(--court-line); border-radius: 12px; overflow: hidden; padding-bottom: 8px; }
  .tm-floor .court { background: transparent; border: 0; border-bottom: 2px solid var(--court-line); border-radius: 0; overflow: visible; }
  .tm-floor .court::before { top: 0; }
  .tm-floor .lanes { position: relative; margin-top: 0; padding: 32px 8px 0; }
  .tm-floor .lanes::before { content: ""; position: absolute; left: 50%; top: -30px; width: 58px; height: 58px; transform: translateX(-50%);
    border: 2px solid var(--court-line); border-radius: 50%; background: var(--court-key); clip-path: inset(30px 0 0 0); }
  .tm-floor .lanes > * { position: relative; z-index: 1; }
  .tm-floor .lane h3 { color: var(--text-primary); opacity: .75; }
  /* phones: the court runs edge to edge */
  @media (max-width: 560px) {
    .tm-courtcard { margin-left: -16px; margin-right: -16px; border-radius: 0; border-left: 0; border-right: 0; padding-left: 0; padding-right: 0; }
    .tm-courtcard > h2, .tm-courtcard > .tm-hint, .tm-courtcard > .tm-money, .tm-courtcard > button, .tm-courtcard > p { margin-left: 14px; margin-right: 14px; }
    .tm-courtcard > .tm-primary { width: calc(100% - 28px); }
    .tm-courtcard .tm-floor { border-radius: 0; border-left: 0; border-right: 0; }
  }
  .sheet #tmQ { position: sticky; top: -14px; z-index: 1; box-shadow: 0 6px 8px -6px rgba(0,0,0,.25); }
  .tm-input { width: 100%; font: inherit; padding: 10px 12px; border-radius: 12px; border: 1px solid var(--border);
    background: var(--surface-1); color: var(--text-primary); margin: 10px 0; }
  .tm-pick { display: grid; grid-template-columns: 1fr auto; gap: 2px 10px; align-items: center; width: 100%; text-align: left;
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary); border-radius: 12px;
    padding: 10px 12px; margin-bottom: 6px; cursor: pointer; font: inherit; }
  .tm-pick:disabled { opacity: .4; cursor: default; }
  .tm-pv { grid-row: span 2; text-align: right; font-variant-numeric: tabular-nums; }
  .tm-pv b { display: block; font-size: 16px; }
  .tm-pv small, .tm-pm { font-size: 12px; }
  .tm-primary { width: 100%; border: 0; border-radius: 12px; padding: 13px; font: inherit; font-weight: 700; cursor: pointer;
    background: var(--accent); color: #fff; margin-top: 12px; }
  .tm-primary:disabled { background: var(--border); color: var(--text-muted); cursor: default; }
  .tm-danger-bg { background: var(--critical); }
  .tm-money { display: flex; justify-content: space-between; color: var(--text-secondary); font-size: 13px; margin-top: 10px; }
  .tm-slot { width: 31%; max-width: 128px; border: 2px dashed var(--court-line); border-radius: 10px; padding: 12px 4px;
    background: color-mix(in srgb, var(--surface-1) 55%, transparent); color: var(--text-secondary); font: inherit; font-size: 12px; cursor: pointer; }
  .lane .tm-slot { width: calc(25% - 5px); }
  @media (max-width: 420px) { .lane .tm-slot { width: calc(33.3% - 4px); } }
  .tm-slot b { display: block; font-size: 18px; color: var(--accent); }
  #team .chip { touch-action: none; user-select: none; -webkit-user-select: none; cursor: grab; transition: transform .15s ease; }
  #team .tm-setchip { touch-action: auto; cursor: pointer; }
  .tm-lift { opacity: .35; }
  .tm-target { outline: 3px solid var(--series-1) !important; outline-offset: 2px; transform: scale(1.04); }
  .tm-ghost { position: fixed; z-index: 50; pointer-events: none; width: 104px; transform: translate(-50%, -60%) rotate(-3deg);
    box-shadow: 0 10px 24px rgba(0,0,0,.25); }
  .tm-flash { animation: tmflash .6s ease; }
  @keyframes tmflash { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--good) 70%, transparent); } 100% { box-shadow: 0 0 0 12px transparent; } }
  .tm-toast { pointer-events: none; position: fixed; left: 50%; bottom: calc(18px + env(safe-area-inset-bottom, 0px)); transform: translateX(-50%) translateY(20px);
    opacity: 0; background: var(--text-primary); color: var(--surface-1); border-radius: 12px; padding: 10px 14px; font-size: 14px;
    z-index: 60; transition: opacity .2s, transform .2s; max-width: calc(100% - 32px); text-align: center; pointer-events: none; }
  .tm-toast.on { opacity: 1; transform: translateX(-50%) translateY(0); }
  @media (prefers-reduced-motion: reduce) { #team *, .tm-toast { transition: none !important; animation: none !important; } }`;
  document.head.appendChild(css);

  if (typeof P === "undefined" || !GAME()) importFromHash();
  window.TEAM = { render, encode, decode, KEY };
})();
