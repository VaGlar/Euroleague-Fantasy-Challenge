// «Η ομάδα μου» for the public edition: the user's squad is entered by hand and kept
// on the device (plus a backup link); lineup, captain, Turn plan and trades are
// computed in the browser with web/opt.js. Uses the page's helpers ($, esc, nm, f1,
// courtView, P, ...), so it is loaded after the main script.
(function () {
  const KEY = "myteam_v1";
  const NEED = { Guard: 4, Forward: 4, Center: 2, "Head Coach": 1 };
  const POS_GR = { Guard: "Guards", Forward: "Forwards", Center: "Centers", "Head Coach": "Coach" };
  const ROLES = ["5άδα", "6ος", "πάγκος"];
  let draft = null;          // team being edited
  let view = "plan";         // plan | game
  let editRoles = null;      // {id: role} while setting the lineup as in the game
  let editCap = null;

  const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } };
  const save = (t) => { try { t.updated = new Date().toISOString(); localStorage.setItem(KEY, JSON.stringify(t)); } catch (e) {} };
  const row = (id) => P.players.find((p) => p.fantasy_id === id);
  const key = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  // ------------------------------------------------------------ backup link
  function encode(t) {
    const j = JSON.stringify({ p: t.players.map((x) => [x.id, x.price]), b: t.bank, r: t.roles || null, c: t.captain ?? null });
    return btoa(unescape(encodeURIComponent(j))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function decode(code) {
    const j = JSON.parse(decodeURIComponent(escape(atob(code.replace(/-/g, "+").replace(/_/g, "/")))));
    return { players: j.p.map(([id, price]) => ({ id, price })), bank: j.b, roles: j.r, captain: j.c };
  }
  function importFromHash() {
    const m = location.hash.match(/[#&]t=([A-Za-z0-9_-]+)/);
    if (!m) return;
    try {
      const t = decode(m[1]);
      if (confirm("Επαναφορά της ομάδας από τον σύνδεσμο; (αντικαθιστά την ομάδα σε αυτή τη συσκευή)")) save(t);
    } catch (e) { alert("Ο σύνδεσμος ομάδας δεν είναι έγκυρος."); }
    history.replaceState(null, "", location.pathname + location.search);
  }

  // ------------------------------------------------------------ helpers
  function squadRows(t) {  // saved team -> rows with model data (unknown ids dropped)
    return t.players.map((x) => { const r = row(x.id); return r ? { ...r, id: x.id, price: x.price ?? r.price } : null; }).filter(Boolean);
  }
  function optPlayer(r, t, inRound) {
    const played = r.actual != null;
    return { id: r.id, position: r.position, price: r.price, x_h: r.x_h ?? 0,
      x_now: inRound && played ? r.actual : (r.x_now ?? 0), turn: r.turn, played: inRound && played,
      cur_role: (t.roles || {})[r.id] || (r.position === "Head Coach" ? "coach" : "πάγκος"),
      cur_captain: t.captain === r.id };
  }
  const counts = (ps) => Object.fromEntries(Object.keys(NEED).map((k) => [k, ps.filter((p) => p.position === k).length]));
  const cost = (t) => t.players.reduce((a, x) => a + (Number(x.price) || 0), 0);
  const rolesValid = (roles, cap, rows) => {
    const five = rows.filter((r) => roles[r.id] === "5άδα");
    return five.length === 5 && rows.filter((r) => roles[r.id] === "6ος").length === 1
      && ["Guard", "Forward", "Center"].every((pos) => five.some((r) => r.position === pos))
      && five.some((r) => r.id === cap);
  };

  // ------------------------------------------------------------ editor
  function editor(best) {
    const ps = draft.players.map((x) => ({ ...x, r: row(x.id) })).filter((x) => x.r);
    const c = counts(ps.map((x) => x.r));
    const done = Object.keys(NEED).every((k) => c[k] === NEED[k]);
    const total = ps.reduce((a, x) => a + (Number(x.price) || 0), 0);
    const bank = draft.bank ?? Math.max(0, 100 - total);
    const group = (pos) => `<h3 style="font-size:13px;margin:12px 0 4px">${POS_GR[pos]} <span class="muted">${c[pos]}/${NEED[pos]}</span></h3>
      ${ps.filter((x) => x.r.position === pos).map((x) => `<div class="game" style="grid-template-columns:1fr auto auto;align-items:center">
        <div><b>${esc(nm(x.r.name))}</b> <span class="muted">${esc(x.r.team)}</span></div>
        <label class="muted" style="font-size:12px">τιμή <input class="tp" data-id="${x.id}" value="${x.price ?? ""}" inputmode="decimal" style="width:62px"></label>
        <button class="linkbtn" data-rm="${x.id}" title="αφαίρεση">✕</button></div>`).join("")}`;
    return `<div class="card"><h2>${load() ? "Επεξεργασία ομάδας" : "Φτιάξε την ομάδα σου"}</h2>
      <p class="muted" style="margin-top:0">Βάλε τους 11 παίκτες σου όπως στο παιχνίδι (4 G, 4 F, 2 C, 1 coach). Η τιμή συμπληρώνεται με τη σημερινή· διόρθωσέ τη αν χρειάζεται.</p>
      <input id="tsearch" placeholder="Αναζήτηση παίκτη ή coach…" autocomplete="off" style="width:100%">
      <div id="tres" class="games" style="margin-top:6px"></div>
      ${Object.keys(NEED).map(group).join("")}
      <div class="filters" style="margin-top:12px;align-items:center">
        <label class="chk">Υπόλοιπο (cr) <input id="tbank" inputmode="decimal" value="${f1(bank)}" style="width:70px"></label>
        <span class="muted">Κόστος ομάδας: <b>${f1(total)}</b> cr</span></div>
      <div class="filters" style="margin-top:8px">
        <button id="tsave" type="button" class="seg" style="padding:8px 14px;${done ? "" : "opacity:.5"}" ${done ? "" : "disabled"}>💾 Αποθήκευση</button>
        ${load() ? '<button id="tcancel" type="button" class="linkbtn">Άκυρο</button><button id="tdel" type="button" class="linkbtn" style="color:var(--critical)">Διαγραφή ομάδας</button>' : ""}
      </div></div>`;
  }
  function bindEditor(best) {
    const results = () => {
      const q = key($("#tsearch").value).trim();
      const have = new Set(draft.players.map((x) => x.id));
      const c = counts(draft.players.map((x) => row(x.id)).filter(Boolean));
      const hits = q.length < 2 ? [] : P.players.filter((p) => p.fantasy_id != null && !have.has(p.fantasy_id)
        && key(p.name).includes(q)).slice(0, 8);
      $("#tres").innerHTML = hits.map((p) => { const full = c[p.position] >= NEED[p.position];
        return `<div class="game" data-add="${p.fantasy_id}" style="cursor:${full ? "default" : "pointer"};${full ? "opacity:.45" : ""}">
          <div><b>${esc(nm(p.name))}</b> <span class="muted">${esc(p.team)} · ${esc(p.position)}</span></div>
          <div class="gv"><b>${f1(p.price)}</b><small>${full ? "γεμάτο" : "cr"}</small></div></div>`; }).join("");
    };
    $("#tsearch").addEventListener("input", results);
    $("#tres").addEventListener("click", (e) => {
      const el = e.target.closest("[data-add]"); if (!el) return;
      e.stopPropagation();
      const r = row(Number(el.dataset.add));
      const c = counts(draft.players.map((x) => row(x.id)).filter(Boolean));
      if (!r || c[r.position] >= NEED[r.position]) return;
      draft.players.push({ id: r.fantasy_id, price: r.price });
      render(best); $("#tsearch").focus();
    });
    $("#team").querySelectorAll("[data-rm]").forEach((b) => b.onclick = () => {
      draft.players = draft.players.filter((x) => x.id !== Number(b.dataset.rm)); render(best);
    });
    $("#team").querySelectorAll("input.tp").forEach((inp) => inp.onchange = () => {
      const x = draft.players.find((y) => y.id === Number(inp.dataset.id));
      const v = parseFloat(String(inp.value).replace(",", "."));
      if (x) x.price = isNaN(v) ? null : v;
      render(best);
    });
    $("#tbank").onchange = () => { const v = parseFloat(String($("#tbank").value).replace(",", ".")); draft.bank = isNaN(v) ? null : v; };
    $("#tsave").onclick = () => {
      const old = load() || {};
      const ids = new Set(draft.players.map((x) => x.id));
      const roles = old.roles ? Object.fromEntries(Object.entries(old.roles).filter(([id]) => ids.has(Number(id)))) : null;
      const total = cost(draft);
      save({ players: draft.players, bank: Math.round((draft.bank ?? Math.max(0, 100 - total)) * 10) / 10,
        roles: roles && Object.keys(roles).length === 11 ? roles : null,
        captain: ids.has(old.captain) ? old.captain : null });
      draft = null; render(best);
    };
    if ($("#tcancel")) $("#tcancel").onclick = () => { draft = null; render(best); };
    if ($("#tdel")) $("#tdel").onclick = () => {
      if (confirm("Διαγραφή της ομάδας από αυτή τη συσκευή;")) { try { localStorage.removeItem(KEY); } catch (e) {} draft = null; render(best); }
    };
  }

  // ------------------------------------------------------------ roles editor («όπως στο παιχνίδι»)
  function rolesEditor(rows) {
    const court = rows.filter((r) => r.position !== "Head Coach");
    const ok = rolesValid(editRoles, editCap, court);
    return `<div class="card"><h2>Η πεντάδα σου στο παιχνίδι</h2>
      <p class="muted" style="margin-top:0">Όρισε ρόλους όπως είναι τώρα στο παιχνίδι: 5 στην πεντάδα (με G, F, C), 1 έκτος, 4 πάγκος, και τον αρχηγό (★).</p>
      <div class="games">${court.map((r) => `<div class="game" style="grid-template-columns:1fr auto;align-items:center">
        <div><b>${esc(nm(r.name))}</b> <span class="muted">${esc((r.position || "")[0])}${r.turn ? ` · T${r.turn}` : ""}</span></div>
        <div class="seg" style="margin:0">${ROLES.map((ro) => `<button data-rid="${r.id}" data-role="${ro}" class="${editRoles[r.id] === ro ? "on" : ""}">${ro === "5άδα" ? "5" : ro === "6ος" ? "6ος" : "Π"}</button>`).join("")}
          <button data-cap="${r.id}" class="${editCap === r.id ? "on" : ""}" title="αρχηγός">★</button></div></div>`).join("")}</div>
      <div class="filters" style="margin-top:10px"><button id="rsave" class="seg" style="padding:8px 14px;${ok ? "" : "opacity:.5"}" ${ok ? "" : "disabled"}>💾 Αποθήκευση</button>
        <button id="rcancel" class="linkbtn">Άκυρο</button>
        <span class="muted">${editRolesSummary(court)}</span></div></div>`;
  }
  function editRolesSummary(court) {
    const n = (ro) => court.filter((r) => editRoles[r.id] === ro).length;
    return `πεντάδα ${n("5άδα")}/5 · 6ος ${n("6ος")}/1 · πάγκος ${n("πάγκος")}/4`;
  }

  // ------------------------------------------------------------ main view
  function teamView(t, best) {
    const rows = squadRows(t);
    if (rows.length !== 11) {
      return `<div class="card warn"><h2>Κάποιοι παίκτες σου δεν βρέθηκαν</h2><p>Πάτα «Επεξεργασία» και διόρθωσε την ομάδα (${rows.length}/11).</p>
        <button id="tedit" class="linkbtn">Επεξεργασία</button></div>`;
    }
    const started = rows.some((r) => r.actual != null);
    const hasRoles = t.roles && Object.keys(t.roles).length === 11;
    const inRound = started && hasRoles;
    const sq = rows.map((r) => optPlayer(r, t, inRound));
    const res = ELFOPT.lineup(sq, { inRound });
    let team = res ? res.team : [], plan = [];
    if (res && !inRound) ({ team, plan } = ELFOPT.deferLaterTurns(res.team));
    const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
    const planList = team.map((p) => ({ ...byId[p.id], id: p.id, role: p.role, captain: p.captain }));
    const gameList = hasRoles ? rows.map((r) => ({ ...r, role: r.position === "Head Coach" ? "coach" : t.roles[r.id], captain: t.captain === r.id })) : [];
    if (!hasRoles) view = "plan";
    const cur = view === "game" ? gameList : planList;
    const other = Object.fromEntries((view === "game" ? planList : gameList).map((p) => [p.id, p.role]));
    const diff = hasRoles && planList.some((p) => other[p.id] !== undefined && (other[p.id] !== p.role))
      || (hasRoles && planList.find((p) => p.captain)?.id !== t.captain);
    const planLines = plan.map((pl) => `<li>🕐 <b>Πριν το T${pl.bench.turn}</b>: αν ο ${esc(surname(byId[pl.start.id].name))}
      φέρει κάτω από ${Math.round(pl.bench.x_now)}, βάλε τον ${esc(surname(byId[pl.bench.id].name))}.</li>`).join("");
    // trades
    const ti = P.trade_info || { round: P.round, max_trades: 4, min_gain: 2 };
    const pool = P.players.filter((p) => p.fantasy_id != null && p.price != null)
      .map((p) => ({ id: p.fantasy_id, position: p.position, price: p.price, x_h: p.x_h ?? 0, x_now: p.x_now ?? 0 }));
    const trs = ELFOPT.transfers(rows.map((r) => ({ id: r.id, position: r.position, price: Number(r.price) || 0, x_h: r.x_h ?? 0, x_now: r.x_now ?? 0 })),
      pool, Number(t.bank) || 0, { maxTrades: ti.max_trades, minGain: ti.min_gain });
    const lim = ti.max_trades > 4 ? "απεριόριστες" : "έως 4";
    const trHtml = trs.pairs.length ? `<p class="up">+${f1(trs.gain)} σταθμισμένα xPTS · υπόλοιπο μετά: ${f1(trs.bankAfter)} cr</p>
      <div class="games">${trs.pairs.map((pr, i) => { const o = byId[pr.out.id], n = row(pr.in.id);
        return `<div class="game" style="grid-template-columns:1fr auto;align-items:center">
          <div><span data-pid="${esc(o.person_id)}" style="cursor:pointer">${esc(nm(o.name))}</span> ➜ <b data-pid="${esc(n.person_id)}" style="cursor:pointer">${esc(nm(n.name))}</b>
            <div class="gs">${esc(o.position)} · ${f1(pr.out.price)} → ${f1(pr.in.price)} cr · ${esc(n.team)}${n.turn ? ` · T${n.turn}` : ""}</div></div>
          <button class="linkbtn" data-did="${i}">✓ Την έκανα</button></div>`; }).join("")}</div>
      ${trs.pairs.length > 1 ? '<button class="linkbtn" id="didall">✓ Τις έκανα όλες</button>' : ""}`
      : `<p>Καμία αλλαγή δεν αξίζει αυτή τη στιγμή (όριο: +${f1(ti.min_gain)} xPTS ανά αλλαγή).</p>`;
    const standalone = window.navigator.standalone || matchMedia("(display-mode: standalone)").matches;
    const html = `<div class="card"><h2>Η ομάδα μου · Υπόλοιπο ${f1(t.bank)} cr</h2>
      <div class="filters"><button id="tedit" class="linkbtn">✏️ Επεξεργασία / αντικατάσταση</button>
        <button id="troles" class="linkbtn">🧩 Πεντάδα όπως στο παιχνίδι</button>
        <button id="tbackup" class="linkbtn">🔗 Αντίγραφο ασφαλείας</button></div>
      ${!hasRoles ? `<p class="warn" style="padding-left:8px">Όρισε την πεντάδα σου όπως είναι στο παιχνίδι για να βλέπεις διαφορές και προτάσεις μέσα στην αγωνιστική.
        <br><button id="tasplan" class="linkbtn">✓ Είναι ίδια με την πρόταση</button> <button id="troles2" class="linkbtn">Όρισε χειροκίνητα</button></p>` : ""}
      ${started && !hasRoles ? `<p class="muted">Η αγωνιστική έχει ξεκινήσει· χωρίς την πεντάδα σου δεν μπορώ να εφαρμόσω τους κανόνες μέσα στην αγωνιστική.</p>` : ""}
      ${hasRoles ? `<div class="seg"><button data-v="plan" class="${view === "plan" ? "on" : ""}">Πρόταση</button><button data-v="game" class="${view === "game" ? "on" : ""}">Στο παιχνίδι</button></div>` : ""}
      ${courtView(cur, hasRoles ? other : null)}
      ${diff && view === "plan" ? `<p class="warn" style="padding-left:8px">Η πρόταση διαφέρει από την πεντάδα σου στο παιχνίδι (διακεκομμένο πλαίσιο).
        Κάνε τις αλλαγές στο παιχνίδι και μετά <button id="tapplied" class="linkbtn">✓ Τις έκανα</button></p>` : ""}
      ${planLines ? `<ul class="plan">${planLines}</ul>` : ""}
      ${inRound ? '<p class="muted">Μέσα στην αγωνιστική: όποιος έπαιξε μπορεί μόνο να βγει στον πάγκο· το x2 μόνο σε παίκτη που δεν έχει παίξει.</p>' : ""}
      ${standalone ? "" : '<p class="muted">📱 Για να μη χαθεί η ομάδα, βάλε την εφαρμογή στην οθόνη σου (<button class="linkbtn" style="padding:0" onclick="installGuide(true)">οδηγίες</button>) ή κράτα τον σύνδεσμο αντιγράφου ασφαλείας.</p>'}</div>
      <div class="card"><h2>Προτεινόμενες αλλαγές για την αγωνιστική ${ti.round} <span class="muted">(${lim})</span></h2>${trHtml}
        <p class="muted">Κάνε τις μεταγραφές στο παιχνίδι και πάτα «✓» για να ενημερωθεί η ομάδα σου εδώ.</p></div>`;
    return { html, planList, trs };
  }

  function applyTrade(t, pr) {
    const i = t.players.findIndex((x) => x.id === pr.out.id);
    if (i < 0) return;
    t.players[i] = { id: pr.in.id, price: pr.in.price };
    t.bank = Math.round(((Number(t.bank) || 0) + pr.out.price - pr.in.price) * 10) / 10;
    if (t.roles) { t.roles[pr.in.id] = t.roles[pr.out.id]; delete t.roles[pr.out.id]; }
    if (t.captain === pr.out.id) t.captain = null;
  }

  function render(best) {
    let html = "";
    const t = load();
    if (draft || !t) {
      if (!draft) draft = { players: [], bank: null };
      html = editor(best);
      $("#team").innerHTML = html + bestCard(best);
      bindEditor(best);
      return;
    }
    if (editRoles) {
      $("#team").innerHTML = rolesEditor(squadRows(t));
      $("#team").querySelectorAll("[data-rid]").forEach((b) => b.onclick = () => { editRoles[b.dataset.rid] = b.dataset.role; render(best); });
      $("#team").querySelectorAll("[data-cap]").forEach((b) => b.onclick = () => { editCap = Number(b.dataset.cap); render(best); });
      $("#rsave").onclick = () => {
        const roles = { ...editRoles };
        squadRows(t).filter((r) => r.position === "Head Coach").forEach((r) => { roles[r.id] = "coach"; });
        save({ ...t, roles, captain: editCap }); editRoles = null; editCap = null; view = "game"; render(best);
      };
      $("#rcancel").onclick = () => { editRoles = null; editCap = null; render(best); };
      return;
    }
    const v = teamView(t, best);
    $("#team").innerHTML = (typeof v === "string" ? v : v.html) + bestCard(best);
    const on = (id, fn) => { const el = $("#" + id); if (el) el.onclick = fn; };
    on("tedit", () => { draft = { players: t.players.map((x) => ({ ...x })), bank: t.bank }; render(best); });
    const startRoles = () => {
      const rows = squadRows(t);
      editRoles = Object.fromEntries(rows.filter((r) => r.position !== "Head Coach").map((r) => [r.id, (t.roles || {})[r.id] || "πάγκος"]));
      editCap = t.captain; render(best);
    };
    on("troles", startRoles); on("troles2", startRoles);
    const takePlan = () => {
      const roles = Object.fromEntries(v.planList.map((p) => [p.id, p.role]));
      save({ ...t, roles, captain: v.planList.find((p) => p.captain)?.id ?? null }); view = "game"; render(best);
    };
    on("tasplan", takePlan); on("tapplied", takePlan);
    on("tbackup", async () => {
      const link = location.origin + location.pathname + "#t=" + encode(t);
      try { await navigator.clipboard.writeText(link); alert("Ο σύνδεσμος αντιγράφηκε. Κράτα τον (π.χ. στις σημειώσεις) — ανοίγοντάς τον σε άλλη συσκευή επανέρχεται η ομάδα σου."); }
      catch (e) { prompt("Αντίγραψε και κράτα αυτόν τον σύνδεσμο:", link); }
    });
    $("#team").querySelectorAll(".seg button[data-v]").forEach((b) => b.onclick = () => { view = b.dataset.v; render(best); });
    $("#team").querySelectorAll("[data-did]").forEach((b) => b.onclick = () => {
      const pr = v.trs.pairs[Number(b.dataset.did)];
      if (!confirm(`Έκανες στο παιχνίδι: ${nm(row(pr.out.id).name)} ➜ ${nm(row(pr.in.id).name)};`)) return;
      applyTrade(t, pr); save(t); render(best);
    });
    on("didall", () => {
      if (!confirm(`Έκανες και τις ${v.trs.pairs.length} μεταγραφές στο παιχνίδι;`)) return;
      v.trs.pairs.forEach((pr) => applyTrade(t, pr)); save(t); render(best);
    });
  }
  function bestCard(best) {
    if (!best) return "";
    return `<div class="card"><h2>Βέλτιστη ομάδα από το μηδέν · ${f1(best.cost)} cr</h2>
      <p class="muted">Με απεριόριστες αλλαγές (π.χ. μετά τις αγωνιστικές 6, 13, 18…).</p>
      ${courtView(best.team.map((p) => ({ ...p, actual: null })), null)}</div>`;
  }

  importFromHash();
  window.TEAM = { render, encode, decode, KEY };
})();
