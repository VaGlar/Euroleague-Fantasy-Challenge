// «Η ομάδα μου» for both editions.
//   public (Coach Dime): the team is entered by hand and lives on the device
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
  const DAYS = L(["Κυριακή", "Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο"], ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]);
  let mode = null;          // null | "setup"
  let setup = null;         // {players: [{id, price}]} while setting up
  // ✕ as in the game: players taken off before their replacements are picked. Only in memory, never saved:
  // the saved team always has 11 (a refresh brings back the last full team). {out: [ids], picks: {outId: inId}}
  let sell = null;
  let cache = { key: null, trs: null };
  let allSteps = false;      // «+n βήματα ακόμα» opened: it stays open while the user works through them

  // ------------------------------------------------------------ storage
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } };
  const GAME = () => P.edition !== "public";
  const WIDE = () => window.matchMedia("(min-width: 700px)").matches;
  // the to-do list's kinds (kept as their marks inside) drawn with the page's icons (index.html: ico)
  const KIND_ICON = { "🔁": ico("trade"), "🔄": ico("swap"), "★": "★" };
  // every change is a step «Undo» can take back, down to the team at the last lock (the latest turn's first
  // tip-off already passed; before any, the start of the trade window). Saves within a moment are one move.
  const SNAP = ["players", "bank", "roles", "captain", "confirmed", "used"];
  const snapOf = (t) => JSON.parse(JSON.stringify(Object.fromEntries(SNAP.map((k) => [k, t[k] ?? null]))));
  const histRound = () => (P.trade_info || {}).round ?? P.round;
  const lastLock = () => {
    if (typeof athensMs !== "function") return 0;
    const past = (P.turns || []).map((x) => athensMs(x.date, x.first_tip)).filter((ms) => ms <= Date.now());
    return past.length ? Math.max(...past) : 0;
  };
  // this lock period's steps (older saves without a time are kept)
  const liveHist = (t) => { const r = histRound(), lock = lastLock();
    return (t.hist || []).filter((h) => h.round === r && (h.at == null || h.at >= lock)); };
  let inClick = false;                       // true until the current click's handler has finished
  const save = (t, { undoing = false } = {}) => {
    if (t.game) { saveDraft(t); return; }
    try {
      const prev = load();
      const r = histRound();
      t.hist = liveHist({ hist: t.hist || (prev && prev.hist) || [] });
      if (!undoing && !inClick && prev && JSON.stringify(snapOf(prev)) !== JSON.stringify(snapOf(t))) {
        t.hist = [...t.hist, { round: r, at: Date.now(), snap: snapOf(prev) }].slice(-60);
        inClick = true;
        setTimeout(() => { inClick = false; }, 0);
      }
      t.updated = new Date().toISOString();
      localStorage.setItem(KEY, JSON.stringify(t));
      syncLater();
    } catch (e) {}
  };
  const undoSteps = (t) => liveHist(t).length;
  const restore = (t, snap) => { for (const k of SNAP) { if (snap[k] === null) delete t[k]; else t[k] = JSON.parse(JSON.stringify(snap[k])); } };
  // a step that leaves the team as it is now (e.g. a sync brought the same team) is skipped: one tap, one visible change
  function undoLast(t) {
    const hist = liveHist(t), now = JSON.stringify(snapOf(t));
    let h = hist.pop();
    while (h && JSON.stringify(h.snap) === now) h = hist.pop();
    if (!h) return false;
    restore(t, h.snap);
    t.hist = hist;
    save(t, { undoing: true });
    return true;
  }
  // «Undo all»: the team as it was at the last lock (the oldest step of this period)
  function undoAll(t) {
    const hist = liveHist(t);
    if (!hist.length) return false;
    restore(t, hist[0].snap);
    t.hist = [];
    save(t, { undoing: true });
    return true;
  }
  // ------------------------------------------------------------ devices in step (public edition)
  // A code links this device's team to a copy on the server (functions/api/sync): every save goes up a
  // moment later, opening the page (or coming back to it) brings the other device's changes down. If
  // both changed it in between, the newer change wins and the page says so. The backup link stays.
  const SYNC = "tm_sync";
  const syncGet = () => { try { return JSON.parse(localStorage.getItem(SYNC) || "null"); } catch (e) { return null; } };
  const syncSet = (v) => { try { if (v) localStorage.setItem(SYNC, JSON.stringify(v)); else localStorage.removeItem(SYNC); } catch (e) {} };
  const fmtCode = (c) => String(c || "").replace(/(....)(?=.)/g, "$1-");
  let syncTimer = 0, syncBusy = false, onRemote = null;
  async function syncApi(method, code, body) {
    const r = await fetch("api/sync" + (code ? "/" + encodeURIComponent(code) : ""), {
      method, headers: body ? { "content-type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined,
      cache: "no-store" });
    let b = null; try { b = await r.json(); } catch (e) {}
    return { status: r.status, body: b };
  }
  function syncLater() {
    const s = syncGet();
    if (!s || GAME()) return;
    if (!s.dirty) syncSet({ ...s, dirty: true });
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => syncPush(), 1500);   // a burst of changes is one write
  }
  // the watchlist (index.html, «watch» on this device) travels with the team: the newer copy wins, as for the team
  const watchNow = () => { try { return JSON.parse(localStorage.getItem("watch") || "{}") || {}; } catch (e) { return {}; } };
  const withWatch = (t) => (t ? { ...t, watch: watchNow() } : t);
  window.watchChanged = () => {
    if (GAME() || !syncGet()) return;
    const t = load();
    if (t) { t.watch = watchNow(); save(t); }       // a save: newer than the other device's copy, goes up in a moment
  };
  // the server's copy replaces this device's (the newer one wins; the page says so)
  function takeRemote(res, quiet) {
    try { localStorage.setItem(KEY, JSON.stringify(res.data)); } catch (e) {}
    if (res.data && res.data.watch && typeof res.data.watch === "object") {
      try { localStorage.setItem("watch", JSON.stringify(res.data.watch)); } catch (e) {}
      if (typeof watchReload === "function") watchReload();
    }
    const s = syncGet();
    if (s) syncSet({ code: s.code, rev: res.rev, dirty: false });
    if (!quiet) toast(L("Η ομάδα ενημερώθηκε από την άλλη συσκευή", "Team updated from your other device"));
    if (onRemote) onRemote();
  }
  const newer = (a, b) => String((a && a.updated) || "") > String((b && b.updated) || "");
  async function syncPush() {
    const s = syncGet(), t = withWatch(load());
    if (!s || !t || syncBusy) return;
    syncBusy = true;
    try {
      let res = await syncApi("PUT", s.code, { data: t, rev: s.rev });
      if (res.status === 409) {            // the other device wrote meanwhile: the newer change wins
        if (newer(res.body.data, t)) { takeRemote(res.body); return; }
        res = await syncApi("PUT", s.code, { data: t, rev: res.body.rev });
      }
      if (res.status === 200) syncSet({ code: s.code, rev: res.body.rev, dirty: false });
    } catch (e) { /* offline: stays dirty, goes up next time */ } finally { syncBusy = false; }
  }
  async function syncPull() {
    const s = syncGet();
    if (!s || GAME() || syncBusy) return;
    try {
      const res = await syncApi("GET", s.code);
      if (res.status === 404) { syncSet(null); toast(L("Ο κωδικός συγχρονισμού δεν υπάρχει πια· η ομάδα μένει σε αυτή τη συσκευή", "The sync code no longer exists; the team stays on this device")); return; }
      if (res.status !== 200) return;
      const t = load();
      if (res.body.rev > s.rev && !(s.dirty && newer(t, res.body.data))) { takeRemote(res.body); return; }
      if (s.dirty || res.body.rev > s.rev) { syncSet({ ...s, rev: s.dirty ? s.rev : res.body.rev }); syncPush(); }
    } catch (e) {}
  }
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") syncPull(); });
  // link this device: with a new code (its team goes up) or an existing one (that team comes down)
  async function syncNew() {
    const t = withWatch(load());
    if (!t) return null;
    const res = await syncApi("POST", "", { data: t });
    if (res.status !== 201) return res.status;
    syncSet({ code: res.body.code, rev: res.body.rev, dirty: false });
    return 201;
  }
  // the code as typed, a Greek keyboard's look-alike capitals and accents too (cleanCode in functions/api/sync)
  const GREEK_LATIN = { Α: "A", Β: "B", Ε: "E", Ζ: "Z", Η: "H", Ι: "I", Κ: "K", Μ: "M", Ν: "N", Ο: "O", Ρ: "P", Τ: "T", Υ: "Y", Χ: "X" };
  const syncCode = (raw) => String(raw || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase()
    .replace(/[\u0391-\u03a9]/g, (c) => GREEK_LATIN[c] || c).replace(/[^A-Z0-9]/g, "");
  async function syncJoin(raw) {
    const code = syncCode(raw);
    if (code.length !== 12) return 400;
    const res = await syncApi("GET", code);
    if (res.status !== 200) return res.status;
    syncSet({ code, rev: res.body.rev, dirty: false });
    takeRemote(res.body, true);
    return 200;
  }
  // the move to coachdime.com (index.html: moveBar, the #sync= reader): the old address backs the team up
  // on the server (a sync code) and sends the code along; here this device links to it by itself. The
  // Home Screen app finds the code in the cookie iOS copied from the browser when it was added.
  async function backup() {
    if (GAME() || !load()) return null;
    if (!syncGet() && await syncNew() !== 201) return null;
    if (syncGet().dirty) await syncPush();
    return syncGet().code;
  }
  const APP = () => !!(navigator.standalone || matchMedia("(display-mode: standalone)").matches);
  const dropMoveCookie = () => { document.cookie = "cd_sync=; Max-Age=0; Path=/; Secure; SameSite=Lax"; };
  async function adoptMove(justMoved) {
    let code = null;
    try { code = sessionStorage.getItem("move_sync"); sessionStorage.removeItem("move_sync"); } catch (e) {}
    if (!code) { const m = document.cookie.match(/(?:^|;\s*)cd_sync=([A-Z0-9]{12})(?:;|$)/); code = m && m[1]; }
    if (!code || syncGet()) return;
    // a team made here before (not the one the move just brought) is replaced only if the user says so
    if (load() && !justMoved && !confirm(L("Υπάρχει ήδη ομάδα εδώ. Να την αντικαταστήσω με αυτή από την παλιά διεύθυνση;", "There is already a team here. Replace it with the one from the old address?"))) {
      dropMoveCookie(); return; }
    let st = 0;
    try { st = await syncJoin(code); } catch (e) {}
    if (st !== 200) { if (st === 404) dropMoveCookie(); return; }
    // the browser keeps the cookie for the Home Screen app made from it; the app itself needs it no more
    if (APP()) dropMoveCookie();
    setup = null; mode = null;
    const phone = /iPhone|iPad|Android/.test(navigator.userAgent);
    toastSoon(!APP() && phone ? L("Η ομάδα σου ήρθε. Πρόσθεσε το Coach Dime στην οθόνη Αφετηρίας· θα είναι κι εκεί.", "Your team is here. Add Coach Dime to your Home Screen; it will be there too.")
      : L("Η ομάδα σου ήρθε από την παλιά διεύθυνση", "Your team came over from the old address"));
  }
  const syncErr = (st) => st === 503 ? L("Ο συγχρονισμός δεν είναι ακόμα διαθέσιμος", "Sync isn't available yet") : st === 404 ? L("Αυτός ο κωδικός δεν υπάρχει", "This code doesn't exist")
    : st === 429 ? L("Πολλές προσπάθειες από αυτή τη σύνδεση· δοκίμασε ξανά σε μία ώρα", "Too many attempts from this connection; try again in an hour")
    : st === 400 ? L("Ο κωδικός έχει 12 γράμματα/αριθμούς, π.χ. ABCD-EFGH-JKMN", "The code has 12 letters/digits, e.g. ABCD-EFGH-JKMN") : L("Δεν έγινε σύνδεση· δοκίμασε ξανά", "Couldn't connect; try again");
  function syncSheet(done) {
    const s = syncGet(), has = !!load();
    const joinBox = `<label class="muted" for="tmSyncCode">${L("Έχεις κωδικό από την άλλη συσκευή σου;", "Have a code from your other device?")}</label>
      <input id="tmSyncCode" class="tm-input" placeholder="ABCD-EFGH-JKMN" autocomplete="off" autocapitalize="characters">
      <button class="tm-primary" id="tmSyncJoin">${L("Σύνδεση", "Connect")}</button>
      ${has ? `<p class="tm-hint">${L("Η ομάδα αυτής της συσκευής θα αντικατασταθεί από την ομάδα του κωδικού.", "This device's team will be replaced by the code's team.")}</p>` : ""}`;
    sheet(`<div class="sh"><div><h2>${L("Συγχρονισμός συσκευών", "Sync devices")}</h2><div class="muted">${L("Το PC και το κινητό σου με την ίδια ομάδα· κάθε αλλαγή περνά αυτόματα", "Your PC and phone with the same team; every change goes across automatically")}</div></div>
        <button class="x" aria-label="${L("Κλείσιμο", "Close")}" onclick="closePlayer()">×</button></div>
      ${s ? `<p>${L("Ο κωδικός σου:", "Your code:")}</p><p class="tm-code" id="tmSyncShow">${esc(fmtCode(s.code))}</p>
          <button class="tm-primary" id="tmSyncCopy">${L("Αντιγραφή κωδικού", "Copy code")}</button>
          <p class="tm-hint">${L(`Στην άλλη συσκευή: «Η ομάδα μου» → ⋯ Επιλογές → Συγχρονισμός συσκευών → γράψε τον κωδικό.
            Κράτα τον όπως έναν κωδικό: όποιος τον έχει βλέπει και αλλάζει την ομάδα.`, `On the other device: “My team” → ⋯ Options → Sync devices → enter the code.
            Keep it like a password: anyone who has it can see and change the team.`)}</p>
          <button class="linkbtn" id="tmSyncOff" style="display:block;margin:8px auto 0">${L("Αποσύνδεση αυτής της συσκευής", "Disconnect this device")}</button>
          <button class="linkbtn tm-danger" id="tmSyncDel" style="display:block;margin:8px auto 0">${L("Διαγραφή από τον server", "Delete from the server")}</button>`
        : `${has ? `<button class="tm-primary" id="tmSyncNew">${L("Νέος κωδικός για αυτή την ομάδα", "New code for this team")}</button><hr class="tm-sep">` : ""}${joinBox}`}`);
    const on = (i, fn) => { const el = document.getElementById(i); if (el) el.onclick = fn; };
    on("tmSyncNew", async () => { const st = await syncNew(); if (st === 201) syncSheet(done); else toast(syncErr(st)); });
    on("tmSyncJoin", async () => {
      const st = await syncJoin($("#tmSyncCode").value);
      if (st === 200) { closePlayer(); setup = null; mode = null; done(); toast(L("Συνδέθηκε· η ομάδα ήρθε από την άλλη συσκευή", "Connected; the team came from your other device")); }
      else toast(syncErr(st));
    });
    on("tmSyncCopy", async () => toast(await copyText(fmtCode(s.code)) ? L("Ο κωδικός αντιγράφηκε", "Code copied") : fmtCode(s.code)));
    on("tmSyncOff", () => { syncSet(null); closePlayer(); toast(L("Η συσκευή αποσυνδέθηκε· η ομάδα μένει εδώ", "Device disconnected; the team stays here")); });
    // the server's copy deleted (the team stays on this device); the other devices unlink at their next sync
    on("tmSyncDel", async () => {
      if (!confirm(L("Να διαγραφεί η ομάδα από τον server; Σε αυτή τη συσκευή μένει.", "Delete the team from the server? It stays on this device."))) return;
      let st = 0;
      try { st = (await syncApi("DELETE", s.code)).status; } catch (e) {}
      if (st === 204 || st === 404) { syncSet(null); closePlayer(); toast(L("Διαγράφηκε από τον server· η ομάδα μένει εδώ", "Deleted from the server; the team stays here")); }
      else toast(syncErr(st));
    });
  }

  function encode(t) {
    const j = JSON.stringify({ p: t.players.map((x) => [x.id, x.price]), b: t.bank, r: t.roles || null, c: t.captain ?? null, u: t.used ? { round: t.used.round, n: t.used.n } : null });
    return btoa(unescape(encodeURIComponent(j))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function decode(code) {
    const j = JSON.parse(decodeURIComponent(escape(atob(code.replace(/-/g, "+").replace(/_/g, "/")))));
    return { players: j.p.map(([id, price]) => ({ id, price })), bank: j.b, roles: j.r, captain: j.c, used: j.u || null, confirmed: true };
  }
  // paste a backup link (the app on the home screen keeps its own storage, apart from the browser)
  function restoreSheet(done) {
    sheet(`<div class="sh"><div><h2>${L("Επαναφορά ομάδας", "Restore team")}</h2><div class="muted">${L("Επικόλλησε τον σύνδεσμο αντιγράφου (Επιλογές → Αντίγραφο ασφαλείας)", "Paste the backup link (Options → Backup)")}</div></div>
        <button class="x" aria-label="${L("Κλείσιμο", "Close")}" onclick="closePlayer()">×</button></div>
      <textarea id="tmLink" class="tm-input" rows="3" placeholder="https://…#t=…" autocomplete="off"></textarea>
      <button class="tm-primary" id="tmLinkOk">${L("Επαναφορά", "Restore")}</button>`);
    $("#tmLinkOk").onclick = () => {
      const m = String($("#tmLink").value).match(/[#&]t=([A-Za-z0-9_-]+)/);
      try { if (!m) throw new Error(); const t = decode(m[1]); if (!t.players || t.players.length !== 11) throw new Error();
        save(t); closePlayer(); setup = null; mode = null; done(); toast(L("Η ομάδα σου επανήλθε", "Your team is restored")); }
      catch (e) { toast(L("Ο σύνδεσμος δεν είναι έγκυρος — αντίγραψέ τον ολόκληρο", "The link isn't valid — copy all of it")); }
    };
  }
  function importFromHash() {
    const m = location.hash.match(/[#&]t=([A-Za-z0-9_-]+)/);
    if (!m) return;
    try { save(decode(m[1])); toastSoon(L("Η ομάδα σου επανήλθε από τον σύνδεσμο", "Your team is restored from the link")); }
    catch (e) { toastSoon(L("Ο σύνδεσμος ομάδας δεν είναι έγκυρος", "The team link isn't valid")); }
    history.replaceState(null, "", location.pathname + location.search);
  }

  // ------------------------------------------------------------ the draft (personal edition)
  // Trades and ✕ on the game's team are a draft on this device only: the game doesn't change. It is
  // dropped when the game's team changes (an update read the trades made there) or the trade round moves on.
  const DRAFT = "tm_draft";
  const gameSig = (g) => [P.my_team?.trade_round ?? P.round, g.bank, ...g.players.map((x) => x.id).sort((a, b) => a - b)].join(",");
  function saveDraft(t) {
    const g = gameTeam();
    if (!g) return;
    try { localStorage.setItem(DRAFT, JSON.stringify({ sig: gameSig(g), team: snapOf(t) })); } catch (e) {}
    t.draft = true;
  }
  const dropDraft = () => { try { localStorage.removeItem(DRAFT); } catch (e) {} };
  // the game's team, with the draft on top of it if there is one
  function myTeam() {
    const g = gameTeam();
    if (!g) return null;
    let d = null;
    try { d = JSON.parse(localStorage.getItem(DRAFT) || "null"); } catch (e) {}
    if (!d || !d.team) return g;
    if (d.sig !== gameSig(g)) { dropDraft(); return g; }
    const t = { ...g, draft: true };
    restore(t, d.team);
    return t;
  }

  // the personal team, as read from the game at the last update
  function gameTeam() {
    const my = P.my_team;
    if (!my || !(my.players || []).length) return null;
    const real = (my.actual_lineup || []).filter((r) => r.role);
    // the squad as the game sets it (an older update also counted the players sold this round: 14/11)
    const inGame = new Set(real.map((r) => Number(r.fantasy_id)));
    const players = my.players.filter((r) => r.fantasy_id != null && (real.length !== 11 || inGame.has(Number(r.fantasy_id))))
      .map((r) => ({ id: Number(r.fantasy_id), price: r.price }));
    const src = real.length === players.length ? real.map((r) => ({ id: Number(r.fantasy_id), role: r.role, captain: r.captain }))
      : (my.lineup || []).map((p) => ({ id: Number(p.id), role: p.role, captain: p.captain }));
    const roles = Object.fromEntries(src.map((x) => [x.id, x.role]));
    for (const x of players) if (!roles[x.id] && row(x.id)?.position === "Head Coach") roles[x.id] = "coach";
    return { game: true, fromGame: real.length === players.length, name: my.name, players, bank: Number(my.bank) || 0, gain: my.gain ?? null,
      roles, captain: src.find((x) => x.captain)?.id ?? null, confirmed: true };
  }

  // ------------------------------------------------------------ helpers
  const row = (id) => P.players.find((p) => p.fantasy_id === id);
  const key = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const sur = (n) => nm(n).replace(/^\S\. /, "");
  // the round under way by the clock too: the data hear of it only at the next update, after the games
  // (Round 3, 19:08: the screen still offered the trades and «κλείνει 18:59»)
  const turnStart = (n) => { const t = (P.turns || []).find((x) => x.turn === n);
    return t && typeof athensMs === "function" ? athensMs(t.date, t.first_tip) : Infinity; };
  const started = () => P.players.some((p) => p.actual != null) || (P.turns || []).some((t) => turnStart(t.turn) <= Date.now());
  // scored / played: his points of the round are in. The app doesn't lock a player whose game has started
  // (the game does; here it only records what was done there), the round under way only shows a note
  // A player whose team's game of this round is over without points for him didn't play: 0, and he is
  // «played» for the game's rules (no armband, no place in the six). 14/10: Fodzo Dada, a DNP of turn 1,
  // still looked like turn 1's to play, and the turn-aware armband went to him.
  const gameOver = (r) => (P.fixtures || []).some((f) => f.round === P.round && f.played && (f.home === r.team || f.away === r.team));
  const scored = (r) => r.actual != null || gameOver(r);
  const played = scored;
  const pts = (r) => r.actual ?? 0;
  // price: today's (players are sold at it); buy: what the user paid (public edition), for the change only
  function rowsOf(t) {
    return t.players.map((x) => { const r = row(x.id); return r ? { ...r, id: x.id, price: r.price ?? x.price,
      buy: t.game || x.price == null ? null : Number(x.price) } : null; }).filter(Boolean);
  }
  const dPrice = (r) => (r.buy == null || r.price == null ? 0 : Math.round((r.price - r.buy) * 10) / 10);
  const arrow = (d) => (d > 0 ? `<span class="tm-up">▲${f1(d)}</span>` : d < 0 ? `<span class="tm-down">▼${f1(-d)}</span>` : "");
  function optRows(rows, t, inRound) {
    return rows.map((r) => ({ id: r.id, position: r.position, team: r.team, price: Number(r.price) || 0, x_h: r.x_h ?? 0,
      x_now: inRound && scored(r) ? pts(r) : (r.x_now ?? 0), turn: r.turn, played: inRound && played(r),
      cur_role: (t.roles || {})[r.id] || (r.position === "Head Coach" ? "coach" : "πάγκος"), cur_captain: t.captain === r.id }));
  }
  const fiveOk = (roles, rows) => {
    const five = rows.filter((r) => roles[r.id] === "5άδα");
    return five.length === 5 && ["Guard", "Forward", "Center"].every((pos) => five.some((r) => r.position === pos));
  };
  // «· Turn 1/2» as the game shows it: the latest turn already started (by the clock), else the first
  function turnNow() {
    const ts = P.turns || [];
    const cur = [...ts].reverse().find((x) => turnStart(x.turn) <= Date.now()) || ts.find((x) => !x.done) || ts[ts.length - 1];
    return ts.length > 1 && cur ? ` · Turn ${cur.turn}/${ts.length}` : "";
  }
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
  // players the user doesn't want to sell for the round the trades are for
  const KEEP = "tm_keep";
  function kept(ti) {
    try { const k = JSON.parse(localStorage.getItem(KEEP) || "null"); return k && k.round === ti.round ? k.ids : []; } catch (e) { return []; }
  }
  function setKept(ti, ids) { try { localStorage.setItem(KEEP, JSON.stringify({ round: ti.round, ids })); } catch (e) {} }
  // players the user doesn't want to buy for that round («δεν θέλω αυτόν, πρότεινε άλλον»)
  const AVOID = "tm_avoid";
  function avoided(ti) {
    try { const k = JSON.parse(localStorage.getItem(AVOID) || "null"); return k && k.round === ti.round ? k.ids : []; } catch (e) { return []; }
  }
  function setAvoided(ti, ids) { try { localStorage.setItem(AVOID, JSON.stringify({ round: ti.round, ids })); } catch (e) {} }
  const tradeInfo = (t) => t.game ? { round: P.my_team?.trade_round ?? P.round, max_trades: P.my_team?.max_trades ?? 4,
    min_gain: P.trade_info?.min_gain ?? 2 } : (P.trade_info || { round: P.round, max_trades: 4, min_gain: 2 });
  const poolRows = (avoid = []) => P.players.filter((p) => p.fantasy_id != null && p.price != null && !avoid.includes(Number(p.fantasy_id)))
    .map((p) => ({ id: Number(p.fantasy_id), position: p.position, team: p.team, price: p.price, x_h: p.x_h ?? 0, x_now: p.x_now ?? 0 }));
  function tradesFor(t, rows) {
    if (t.game && !t.draft) {
      const my = P.my_team || {}, ti = tradeInfo(t), keep = kept(ti), avoid = avoided(ti);
      if (keep.length || avoid.length) {   // re-plan in the browser (same optimizer, checked against Python)
        const prefs = my.prefs || { keep: [], avoid: [] };
        const k = "g|" + keep.join(",") + "|" + avoid.join(",") + "|" + P.generated;
        if (cache.key !== k) {
          cache = { key: k, trs: ELFOPT.transfers(optRows(rows, t, false), poolRows([...prefs.avoid, ...avoid]), Number(t.bank) || 0,
            { maxTrades: ti.max_trades, minGain: ti.min_gain, keep: [...keep, ...prefs.keep] }) };
          cache.trs.pairs.sort((a, b) => (a.in.price - a.out.price) - (b.in.price - b.out.price));
        }
        return { ti, trs: cache.trs, keep, avoid };
      }
      const pairs = (my.transfers || []).filter((m) => m.out_id != null && m.in_id != null)
        .map((m) => ({ out: { id: Number(m.out_id), price: m.price_out }, in: { id: Number(m.in_id), price: m.price_in } }))
        .sort((a, b) => (a.in.price - a.out.price) - (b.in.price - b.out.price));
      return { ti, trs: { pairs, gain: my.transfer_gain ?? 0 }, keep, avoid };
    }
    const ti = tradeInfo(t), keep = kept(ti), avoid = avoided(ti);
    const prefs = (t.game && P.my_team?.prefs) || { keep: [], avoid: [] };     // preferences.yaml (personal edition)
    const left = Math.max(0, ti.max_trades - usedTrades(t, ti));
    const k = (t.game ? "d|" : "") + t.players.map((x) => `${x.id}:${x.price}`).join(",") + "|" + t.bank + "|" + left + "|" + keep.join(",") + "|" + avoid.join(",") + "|" + P.generated;
    if (cache.key !== k && !left) cache = { key: k, trs: { pairs: [], gain: 0 } };
    if (cache.key !== k) {
      cache = { key: k, trs: ELFOPT.transfers(optRows(rows, t, false), poolRows([...prefs.avoid, ...avoid]), Number(t.bank) || 0,
        { maxTrades: left, minGain: ti.min_gain, keep: [...keep, ...prefs.keep] }) };
      // money-freeing trades first, so the bank never goes negative while making them
      cache.trs.pairs.sort((a, b) => (a.in.price - a.out.price) - (b.in.price - b.out.price));
    }
    return { ti, trs: cache.trs, left, keep, avoid };
  }
  // trades already made for the round the proposal is for (so a done trade isn't re-proposed)
  const usedTrades = (t, ti) => (t.used && t.used.round === ti.round ? t.used.n : 0);
  // the team as it was before this round's first change (trade or «Αλλαγή ομάδας»), if it differs from now
  const roundStart = (t, ti) => (t.used && t.used.round === ti.round && t.used.before ? t.used.before : null);
  const sameTeam = (a, b) => a.players.map((x) => x.id).sort().join() === b.players.map((x) => x.id).sort().join()
    && Number(a.bank) === Number(b.bank);
  // after «💾 Save» the team as set there is the start: the counter alone is nothing to undo
  const atCheckpoint = (t, ti) => !!(t.cp && t.cp.round === ti.round);
  const canUndo = (t, ti) => (usedTrades(t, ti) > 0 && !atCheckpoint(t, ti)) || (!!roundStart(t, ti) && !sameTeam(t, roundStart(t, ti)));
  // «💾 Save»: the team as it is now becomes what «Undo all» brings back (e.g. the previous
  // round's trades, recorded late, are no longer undone with this round's). The trades count stays as it is.
  function checkpoint(t) {
    const ti = tradeInfo(t);
    t.hist = [];
    if (t.used && t.used.round === ti.round) t.used = { ...t.used, before: null };
    t.cp = { round: ti.round, at: Date.now() };
    save(t, { undoing: true });
  }
  // «μου μένουν N μεταγραφές»: the game counts every change of the round, the app only what it saw
  const tradesLeft = (t, ti) => Math.max(0, (ti.max_trades ?? 4) - usedTrades(t, ti));
  function setTradesLeft(t, left) {
    const ti = tradeInfo(t);
    const n = Math.max(0, (ti.max_trades ?? 4) - left);
    t.used = { round: ti.round, n, before: roundStart(t, ti) };
  }
  const leftPicker = (t, ti, id) => ti.max_trades > 4 ? "" : `<label class="tm-left">${L("Trades που σου μένουν", "Trades left")}:
      <select id="${id}">${Array.from({ length: ti.max_trades + 1 }, (_, i) => ti.max_trades - i)
        .map((v) => `<option value="${v}"${v === tradesLeft(t, ti) ? " selected" : ""}>${v}</option>`).join("")}</select></label>`;
  function countTrade(t) {
    const ti = tradeInfo(t);
    const n = usedTrades(t, ti);
    // before the round's first trade, keep the team as it was, so the trades can be undone
    const before = roundStart(t, ti) || JSON.parse(JSON.stringify({ players: t.players, bank: t.bank,
      roles: t.roles || null, captain: t.captain ?? null, confirmed: !!t.confirmed }));
    t.used = { round: ti.round, n: n + 1, before };
  }
  // back to the team before this round's trades (older saves without the snapshot: only the count)
  function undoTrades(t) {
    const b = t.used && t.used.before;
    if (b) Object.assign(t, JSON.parse(JSON.stringify(b)));
    t.used = null;
    return !!b;
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
    const { ti, trs, keep, avoid } = tradesFor(t, rows);
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
    // expected points of the round if the plan is followed (its trades, five, 6th and CAP)
    const lineupPts = team.reduce((a, p) => { const r = aRows.find((x) => x.id === p.id); if (!r) return a;
      const v = inRound && scored(r) ? pts(r) : (r.x_now ?? 0);
      return a + v * (p.role === "πάγκος" ? 0.5 : 1) * (p.captain ? 2 : 1); }, 0);
    // the swaps before a later turn (🕐 below): the later bench player comes in when the early starter
    // scores less, so each pair adds (1 − bench share) × E[max(0, later − early)] (optimize.py's option value)
    const option = turnPlan.reduce((a, x) => a + (1 - ELFOPT.BENCH)
      * ELFOPT.expectedShortfall(x.bench.x_now, x.start.x_now), 0);
    const items = [];
    if (tradesNow) for (const pr of pairs) {
      const o = rows.find((r) => r.id === pr.out.id), n = row(pr.in.id);
      items.push({ kind: "🔁", html: `<b>${esc(sur(o.name))}</b> vs <b>${esc(sur(n.name))}</b>`, why: "",
        keep: o, avoid: n, cmp: [o.person_id, n.person_id], short: !affords(t, pr),
        run: () => { applyTrade(t, pr.out.id, pr.in.id, pr.in.price); save(t); toast(`${sur(o.name)} ➜ ${sur(n.name)} · ${L("υπόλοιπο", "credits left")} ${f1(t.bank)} cr`); } });
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
    const ROLE_NAME = { "5άδα": "Starting five", "6ος": "Sixth man", "πάγκος": "Bench" }, ORDER = { "5άδα": 0, "6ος": 1, "πάγκος": 2 };
    for (const g of groups) {
      const waits = g.some((st) => !t.players.some((x) => x.id === st.in.id) || pendingTrades && !t.players.some((x) => x.id === st.out.id));
      const fin = { ...roles0 };
      for (const st of g) [fin[st.in.id], fin[st.out.id]] = [fin[st.out.id], fin[st.in.id]];
      const moved = [...new Set(g.flatMap((st) => [st.in, st.out]))].filter((r) => fin[r.id] !== roles0[r.id])
        .sort((x, y) => ORDER[fin[x.id]] - ORDER[fin[y.id]]);
      Object.assign(roles0, fin);
      // only players the trades bring in: their place is set when the trade is made (no extra step)
      if (g.every((st) => [st.in, st.out].every((r) => !t.players.some((x) => x.id === r.id)))) continue;
      const first = g[0];
      const html = g.length === 1
        ? `<b>${esc(sur(first.out.name))}</b> vs <b>${esc(sur(first.in.name))}</b>`
        : moved.map((r) => `<b>${esc(sur(r.name))}</b> → ${ROLE_NAME[fin[r.id]]}`).join(" · ");
      items.push({ kind: "🔄", html,
        why: "", wait: waits,
        run: () => { for (const st of g) if (!swap(t, st.in.id, st.out.id, true)) break; } });
    }
    if (targetCap != null && t.captain !== targetCap) {
      const c = aRows.find((r) => r.id === targetCap);
      const ready = t.players.some((x) => x.id === targetCap) && (t.roles || {})[targetCap] === "5άδα";
      items.push({ kind: "★", html: `Captain: <b>${esc(sur(c.name))}</b>`, why: "", wait: !ready,
        run: () => { t.captain = targetCap; save(t); toast(`CAP: ${sur(c.name)}`); } });
    }
    return { rows, items, turnPlan, trs, ti, tradesNow, inRound, aRows, target, targetCap, keep: keep || [], avoid: avoid || [], lineupPts, option };
  }

  // ------------------------------------------------------------ actions on the saved team
  // the credits allow this trade now (sold at today's price): otherwise the others have to go first
  const affords = (t, pr) => (Number(t.bank) || 0) + (Number(row(pr.out.id)?.price ?? pr.out.price) || 0) - (Number(pr.in.price) || 0) >= -0.05;
  const doneBtn = (attr, i) => `<button class="tm-done" ${attr} ${i.short || i.wait ? "disabled" : ""}${
    i.short ? ` title="${L("Δεν φτάνουν τα credits: κάνε πρώτα τα άλλα Trades", "Not enough credits: do the other Trades first")}"` : ""}>✓ ${L("Το έκανα", "Done")}</button>`;
  function applyTrade(t, outId, inId, price) {
    const i = t.players.findIndex((x) => x.id === outId);
    if (i < 0) return;
    const out = t.players[i];
    const outPrice = Number(row(outId)?.price ?? out.price) || 0;   // sold at today's price
    countTrade(t);
    t.players[i] = { id: inId, price };
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
        if (from === "πάγκος") { toast(L(`Ο ${sur(p.name)} έπαιξε από το Bench — μένει εκεί`, `${sur(p.name)} played from the Bench — he stays there`)); return false; }
        if (to !== "πάγκος") { toast(L(`Ο ${sur(p.name)} έχει παίξει — μπορεί μόνο να βγει στο Bench`, `${sur(p.name)} has played — he can only go to the Bench`)); return false; }
      }
    }
    const next = { ...roles, [a]: rb, [b]: ra };
    if (!fiveOk(next, rows)) {
      const five = rows.filter((r) => next[r.id] === "5άδα");
      const miss = ["Guard", "Forward", "Center"].filter((pos) => !five.some((r) => r.position === pos));
      toast(L(`Το Starting five χρειάζεται τουλάχιστον έναν ${miss.map((m) => NAME[m]).join(", ")}`, `The Starting five needs at least one ${miss.map((m) => NAME[m]).join(", ")}`));
      return false;
    }
    t.roles = next;
    if (t.captain && next[t.captain] !== "5άδα") { t.captain = null; toast(L("Ο Captain βγήκε από το Starting five — διάλεξε νέο", "The Captain left the Starting five — pick a new one")); }
    else if (!quiet) toast(`${sur(byId[a].name)} ⇄ ${sur(byId[b].name)}`);
    save(t); render(); flash(a); flash(b);
    return true;
  }
  function flash(id) { requestAnimationFrame(() => document.querySelector(`#team .chip[data-fid="${id}"]`)?.classList.add("tm-flash")); }

  // ------------------------------------------------------------ court
  function chipHtml(r, t, extraCls = "") {
    const isPlayed = scored(r);
    const cap = t && t.captain === r.id;
    return `<div class="chip${cap ? " cap" : ""} ${extraCls}" data-fid="${r.id}" tabindex="0" role="button" aria-label="${esc(nm(r.name))}">
      <div class="ct"><span>${LETTER[r.position] || ""}</span>${r.turn ? `<span class="tb t${Math.min(r.turn, 3)}">T${r.turn}</span>` : ""}</div>
      <div class="cn cnx"><span class="nm">${esc(sur(r.name))}</span>${r.unregistered ? `<span title="${L("εκτός ρόστερ EuroLeague", "not on the EuroLeague roster")}">${ico("roster")}</span>` : inj(r) ? `<span>${ico("medic")}</span>` : ""}${r.price_trend === "up" ? "<span>$</span>" : ""}${typeof fewGames === "function" && fewGames(r) ? `<span class="few" data-info="few" role="button" tabindex="0" aria-label="${L("Τι σημαίνει νέος", "What new means")}">NEW</span>`
        : r.returning ? `<span class="few" data-info="back" role="button" tabindex="0" aria-label="${L("Τι σημαίνει επιστρέφει", "What returning means")}">↩</span>` : ""}</div>
      <div class="cp${isPlayed ? " done" : ""}">${f1(isPlayed ? pts(r) : r.x_now)}</div>
      <div class="cs">${gameOf(r)}${r.price != null ? ` · ${f1(r.price)}${arrow(dPrice(r))}` : ""}</div></div>`;
  }
  function courtHtml(t, rows, pl) {
    const moved = (r) => pl && !pl.tradesNow && pl.target[r.id] && (t.roles || {})[r.id] !== pl.target[r.id] ? "chg" : "";
    const by = (role) => rows.filter((r) => (t.roles || {})[r.id] === role || (role === "coach" && r.position === "Head Coach"));
    const five = by("5άδα");
    const line = (pos) => five.filter((r) => r.position === pos).map((r) => chipHtml(r, t, moved(r))).join("");
    return `<div class="tm-floor"><div class="court"><div class="crow">${line("Center")}</div><div class="crow">${line("Forward")}</div><div class="crow">${line("Guard")}</div></div>
      <div class="lanes"><div class="pair">
        <div class="lane six"><h3>Sixth man</h3><div class="crow">${by("6ος").map((r) => chipHtml(r, t, moved(r))).join("")}</div></div>
        <div class="lane coach"><h3>Head Coach</h3><div class="crow">${by("coach").map((r) => chipHtml(r, t, moved(r))).join("")}</div></div></div>
        <div class="lane bench"><h3>Bench (50% FPT)</h3><div class="crow">${by("πάγκος").sort((a, b) => (b.x_now ?? 0) - (a.x_now ?? 0)).map((r) => chipHtml(r, t, moved(r))).join("")}</div></div></div></div>`;
  }

  // ------------------------------------------------------------ main screen
  function mainView(t, best) {
    const pl = plan(t);
    const rows = pl.rows;
    if (rows.length !== 11) {
      return `<div class="card warn"><h2>${L("Κάποιοι παίκτες δεν βρέθηκαν", "Some players weren't found")} (${rows.length}/11)</h2>
        <p>${L("Μπορεί να άλλαξαν ομάδα ή να έφυγαν από τη λίστα του παιχνιδιού.", "They may have changed team or left the game's list.")}</p><button class="linkbtn" id="tmEdit">${L("Διόρθωση ομάδας", "Fix team")}</button></div>`;
    }
    const items = pl.items;
    const total = rows.reduce((a, r) => { const role = (t.roles || {})[r.id]; const v = scored(r) ? pts(r) : (r.x_now ?? 0);
      return a + v * (role === "πάγκος" ? 0.5 : 1) * (t.captain === r.id ? 2 : 1); }, 0);
    const value = rows.reduce((a, r) => a + (Number(r.price) || 0), 0);
    // as the game: (credits + today's value of the squad) − the 100 of the start (sold players' gains/losses included)
    const gain = t.game ? Math.round((Number(t.gain) || 0) * 10) / 10 : Math.round(((Number(t.bank) || 0) + value - 100) * 10) / 10;
    const head = pl.inRound
      ? `${ico("clock")} Round ${P.round}${turnNow()} ${L("σε εξέλιξη", "in progress")}`
      : `${ico("clock")} Round ${P.round}${turnNow()} · ${L("κλείνει", "locks")} ${deadline()}`;
    const confirm = !t.confirmed ? `<li class="tm-item"><span class="tm-kind">${ico("eye")}</span><span class="tm-what"><b>Your Starting five</b>
        <span class="tm-why">${L("Σύρε τους παίκτες όπως είναι στο παιχνίδι.", "Drag the players to match the game.")}</span>
        ${t.game ? "" : leftPicker(t, pl.ti, "tmLeft")}</span>
        <button class="tm-done" id="tmConfirm">✓ ${L("Είναι ίδια", "It matches")}</button></li>` : "";
    const keepBtn = (o) => `<button class="tm-keep" data-keep="${o.id}" title="${L(`Κράτα τον ${esc(sur(o.name))} αυτό το Round`, `Keep ${esc(sur(o.name))} this Round`)}">${ico("lock")} Keep</button>`;
    const avoidBtn = (n) => n ? `<button class="tm-keep" data-avoid="${n.fantasy_id ?? n.id}" title="${L(`Όχι τον ${esc(sur(n.name))}, πρότεινε άλλον`, `Not ${esc(sur(n.name))}, suggest another`)}">${ico("sync")} Other</button>` : "";
    const who = (id) => { const r = row(id); return esc(sur(r ? r.name : String(id))); };
    const keptLine = (pl.keep.length ? `<p class="tm-kept">${ico("lock")} ${L("Κρατάς", "Keeping")}: ${pl.keep.map((id) =>
        `<b>${who(id)}</b> <button class="linkbtn" data-unkeep="${id}">${L("αναίρεση", "undo")}</button>`).join(" · ")}</p>` : "")
      + (pl.avoid.length ? `<p class="tm-kept">${ico("ban")} ${L("Δεν θέλεις", "Not wanted")}: ${pl.avoid.map((id) =>
        `<b>${who(id)}</b> <button class="linkbtn" data-unavoid="${id}">${L("αναίρεση", "undo")}</button>`).join(" · ")}</p>` : "");
    const lis = items.map((i, n) => `<li class="tm-item${i.kind === "🔁" ? " tm-trade" : ""}"${i.cmp ? ` data-cmp="${esc(i.cmp.join(","))}"` : ""}><span class="tm-kind" aria-hidden="true">${KIND_ICON[i.kind] || i.kind}</span>
        <span class="tm-what">${i.html}${i.why ? `<span class="tm-why">${i.why}</span>` : ""}${i.keep || i.avoid ? `<span class="tm-kbtns">${i.keep ? keepBtn(i.keep) : ""}${i.avoid ? avoidBtn(i.avoid) : ""}</span>` : ""}</span>
        ${t.game && i.kind !== "🔁" ? "" : doneBtn(`data-i="${n}"`, i)}</li>`);
    const steps = [confirm, ...lis].filter(Boolean);
    const todo = steps.length ? `<p class="tm-next-h">${L("Επόμενο βήμα", "Next step")}</p><ul class="tm-list tm-next">${steps[0]}</ul>${steps.length > 1
      ? `<details class="tm-all"${allSteps ? " open" : ""}><summary>+${steps.length - 1} ${L(`${steps.length === 2 ? "βήμα" : "βήματα"} ακόμα`, `more ${steps.length === 2 ? "step" : "steps"}`)}</summary><ul class="tm-list">${steps.slice(1).join("")}</ul></details>` : ""}` : "";
    const turnPlan = pl.turnPlan.map((x) => { const s = pl.aRows.find((r) => r.id === x.start.id), b = pl.aRows.find((r) => r.id === x.bench.id);
      return `<li>${ico("clock")} <b>${L("Πριν το", "Before")} T${x.bench.turn}</b>: ${L(`αν ο ${esc(sur(s.name))} φέρει κάτω από ${Math.round(x.bench.x_now)}, βάλε τον ${esc(sur(b.name))}.`, `if ${esc(sur(s.name))} scores under ${Math.round(x.bench.x_now)}, bring in ${esc(sur(b.name))}.`)}</li>`; }).join("");
    // while the round is under way only swaps and the armband: next round's trades wait for it to end
    const nextTrades = pl.inRound ? "" : !pl.tradesNow && pl.trs.pairs.length ? `<div class="card"><h2>${L("Trades για το Round", "Trades for Round")} ${pl.ti.round}
        <small class="muted">(${pl.ti.max_trades > 4 ? L("απεριόριστα", "unlimited") : `Trades ${usedTrades(t, pl.ti)}/${pl.ti.max_trades}`} · ${L("μετά το τρέχον Round", "after the current Round")})</small></h2>
        <ul class="tm-list">${pl.trs.pairs.map((pr, n) => { const o = rows.find((r) => r.id === pr.out.id), nn = row(pr.in.id);
          return `<li class="tm-item tm-trade" data-cmp="${esc([o.person_id, nn.person_id].join(","))}"><span class="tm-kind">${ico("trade")}</span><span class="tm-what"><b>${esc(sur(o.name))}</b> vs <b>${esc(sur(nn.name))}</b><span class="tm-kbtns">${keepBtn(o)}${avoidBtn(nn)}</span></span>
            ${doneBtn(`data-n="${n}"`, { short: !affords(t, pr) })}</li>`; }).join("")}</ul>${keptLine}</div>`
      : !pl.tradesNow && (pl.keep.length || pl.avoid.length) ? `<div class="card"><h2>${L("Trades για το Round", "Trades for Round")} ${pl.ti.round}</h2><p>${L("Κανένα Trade δεν αξίζει με αυτές τις επιλογές σου.", "No Trade is worth it with these choices of yours.")}</p>${keptLine}</div>` : "";
    const done = !items.length && t.confirmed;
    // the "→" number: the round's expected points when every step is done, the To do list now and the
    // 🕐 swaps before a later turn (their option value); with no steps left the lineup already is the plan
    const planned = (items.length ? pl.lineupPts : total) + pl.option;
    const upd = P.generated ? new Date(P.generated).toLocaleString(LOC, { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "";
    const hint = t.game
      ? L(`Starting five/Captain με <b>/lineup</b> · Trades στο παιχνίδι (εδώ ✓ και ✕ είναι πρόχειρο) · ενημ. ${esc(upd)}`, `Starting five/Captain with <b>/lineup</b> · Trades in the game (here ✓ and ✕ are a draft) · upd. ${esc(upd)}`)
      : "";
    return `<header class="tm-top"><div><h2 class="tm-h">${t.game ? esc(t.name || L("Η ομάδα μου", "My team")) : L("Η ομάδα μου", "My team")}</h2>
        <div class="muted"><button class="tm-trades" id="tmBankEdit" type="button" title="${L("Διόρθωσε τα credits σου", "Correct your credits")}">Credits <b>${f1(t.bank)}/${f1(Number(t.bank) + value)}</b> ✎</button>${gain ? ` <span class="${gain > 0 ? "tm-up" : "tm-down"}">(${gain > 0 ? "+" : "−"}${f1(Math.abs(gain))} gain)</span>` : ""} · ${pl.ti.max_trades <= 4 && t.game ? `<button class="tm-trades" id="tmTrades" type="button" title="${L("Άλλαξε πόσα Trades σου μένουν", "Change how many Trades you have left")}">Trades <b>${usedTrades(t, pl.ti)}/${pl.ti.max_trades}</b> ✎</button>`
          : `<span class="tm-tcount">Trades <b>${usedTrades(t, pl.ti)}/${pl.ti.max_trades > 4 ? "∞" : pl.ti.max_trades}</b></span>`}</div>
        <div class="muted">xFPT <b>${f1(total)}</b>${Math.abs(planned - total) >= 0.05
          ? ` → <b class="tm-planned" title="${L("Οι πόντοι στο τέλος του Round αν κάνεις όλα τα βήματα", "Your points at the end of the Round if you do every step")}${pl.turnPlan.length ? L(", και τις αλλαγές πριν το επόμενο Turn", ", and the swaps before the next Turn") : ""}">${f1(planned)}</b>` : ""}${typeof earlyII === "function" ? earlyII() : ""}</div>
        <div class="tm-dead">${head}</div>${clubWarn(rows, pl.trs)}</div>
        ${t.game ? (t.draft ? `<div class="tm-right"><div class="tm-toolbar" role="toolbar"><button id="tmDraftX" title="${L("Η ομάδα όπως είναι στο παιχνίδι", "The team as it is in the game")}">↩ ${L("Ακύρωση Trades", "Cancel Trades")}</button></div></div>` : "")
          : `<div class="tm-right">${undoBar(t)}<div class="tm-morewrap"><button class="tm-more" id="tmMore" aria-haspopup="menu">⋯ ${L("Επιλογές", "Options")}</button><div id="tmMenu"></div></div></div>`}</header>
      <div class="tm-cols"><div class="tm-colL">
      <div class="card" id="tmTodo"><h2>To do <small class="muted">${items.length ? `${items.length} ${items.length === 1 ? L("βήμα", "step") : L("βήματα", "steps")}` : ""}</small></h2>
        ${pl.inRound && !t.game ? `<p class="tm-live">${ico("clock")} ${L(`Το Round ${P.round} τρέχει. Αν έκανες Trades στο παιχνίδι, έλεγξε ότι είναι και εδώ
          (πάτα τον παίκτη → Trade ή ✕), ώστε το επόμενο Round να ξεκινήσει από τη σωστή ομάδα.`, `Round ${P.round} is under way. If you made Trades in the game, check they are here too
          (tap the player → Trade or ✕), so the next Round starts from the right team.`)}</p>` : ""}
        ${done ? `<div class="tm-ready">${ico("check")} ${L("Έτοιμος για το Round", "Ready for the Round")}${pl.turnPlan.length
          ? `<span class="tm-why">${L(`Μένει να αποφασίσεις ${pl.turnPlan.length === 1 ? "μία αλλαγή" : `${pl.turnPlan.length} αλλαγές`} πριν το επόμενο Turn`, `${pl.turnPlan.length === 1 ? "One swap" : `${pl.turnPlan.length} swaps`} left to decide before the next Turn`)} (${ico("clock")} ${L("παρακάτω", "below")}).</span>` : ""}</div>` : `${todo}`}
        ${pl.tradesNow ? keptLine : ""}
        ${turnPlan ? `<ul class="plan">${turnPlan}</ul>` : ""}
        ${hint ? `<p class="tm-hint">${hint}</p>` : ""}</div>
      ${nextTrades}</div>
      <div class="tm-colR">${items.length && !done ? `<button class="tm-steps" id="tmSteps" type="button">${ico("roster")} <b>${items.length} ${items.length === 1 ? L("βήμα", "step") : L("βήματα", "steps")}</b> ${L("για το Round", "for Round")} ${pl.ti.round} <span aria-hidden="true">↓</span></button>` : ""}<div class="card tm-courtcard"><h2>${t.game ? (t.draft ? L("Πρόχειρο", "Draft") : t.fromGame ? L("Στο παιχνίδι τώρα", "In the game now") : L("Η πρόταση", "The proposal")) : "Your Starting five"}${t.game ? ` <small class="muted">${t.draft ? L("με τα Trades σου · το παιχνίδι δεν αλλάζει", "with your Trades · the game doesn't change") : t.fromGame ? L("διακεκομμένο = αλλάζει", "dashed = changes") : L("δεν διαβάστηκε το Starting five", "the Starting five wasn't read")}</small>` : ""}</h2>
        ${courtHtml(t, rows, t.game ? pl : null)}</div></div></div>
      ${bestCard(best)}`;
  }

  // ⚠️ 4+ players from one club (the game allows 6): one bad night of that team hits them all together,
  // and they all play in the same Turn. Now, and after the proposed trades if they add to it.
  const CLUB_WARN = 4;
  function clubWarn(rows, trs) {
    const count = (list) => list.reduce((a, p) => (p.team && p.position !== "Head Coach" ? (a[p.team] = (a[p.team] || 0) + 1, a) : a), {});
    const now = count(rows), next = trs && trs.pairs && trs.pairs.length ? count(trs.squad || []) : {};
    const out = [];
    for (const [club, n] of Object.entries(now)) if (n >= CLUB_WARN) out.push(L(`${n} παίκτες ${esc(tc(club))}`, `${n} ${esc(tc(club))} players`));
    for (const [club, n] of Object.entries(next)) if (n >= CLUB_WARN && n > (now[club] || 0)) out.push(L(`με τα Trades ${n} παίκτες ${esc(tc(club))}`, `with the Trades ${n} ${esc(tc(club))} players`));
    return out.length ? `<div class="tm-warn" title="${L("Μία κακή βραδιά της ομάδας τους χτυπάει όλους μαζί, και παίζουν στο ίδιο Turn", "One bad night for their team hits them all at once, and they play in the same Turn")}">${ico("warn")} ${out.join(" · ")}</div>` : "";
  }

  // ------------------------------------------------------------ player actions
  const ROLE_LABEL = { "5άδα": "Starting five", "6ος": "Sixth man", "πάγκος": "Bench" };
  function playerSheet(t, id) {
    const rows = rowsOf(t), r = rows.find((x) => x.id === id);
    if (!r) return;
    const role = r.position === "Head Coach" ? "coach" : (t.roles || {})[id];
    const canCap = role === "5άδα" && t.captain !== id && !(played(r) && t.captain !== id);
    sheet(`<div class="sh"><div><h2>${esc(nm(r.name))}</h2>
        <div class="muted">${esc(tc(r.team))} · ${NAME[r.position]} · ${L("τώρα", "now")} ${f1(r.price)} cr${r.buy != null ? ` · ${L("αγορά", "bought")} ${f1(r.buy)}${dPrice(r) ? ` (${dPrice(r) > 0 ? "+" : "−"}${f1(Math.abs(dPrice(r)))})` : ""}` : ""}${r.popularity != null ? ` · POP ${f1(r.popularity)} %` : ""}${r.turn ? ` · Turn ${r.turn}` : ""}${role && role !== "coach" ? ` · ${esc(ROLE_LABEL[role] || role)}` : ""}</div></div>
        <button class="x" aria-label="${L("Κλείσιμο", "Close")}" onclick="closePlayer()">×</button></div>
      <div class="kpis"><div class="kpi"><b>${f1(scored(r) ? pts(r) : r.x_now)}</b><span>${scored(r) ? (r.actual == null ? L("δεν έπαιξε", "didn't play") : "points") : "xFPT"}</span></div>
        <div class="kpi"><b>${f1(xf3(r))}</b><span>xFPT3</span></div><div class="kpi"><b>${r.value == null ? "–" : r.value.toFixed(2)}</b><span>xFPT3/cr</span></div></div>
      <div class="tm-acts">
        ${t.game ? "" : r.position !== "Head Coach" ? `<button class="tm-act" id="aCap" ${canCap ? "" : "disabled"}><span>★</span><div>Captain</div></button>
        <button class="tm-act" id="aSwap"><span>⇄</span><div>Substitute</div></button>` : ""}
        <button class="tm-act" id="aRep"><span>${ico("trade")}</span><div>Trade</div></button>
        <button class="tm-act" id="aOut"><span>✕</span><div>Remove</div></button>
        ${t.game ? "" : `<button class="tm-act" id="aPrice"><span>✎</span><div>Correct price</div></button>`}
      </div>`);
    const on = (i, fn) => { const el = document.getElementById(i); if (el) el.onclick = fn; };
    on("aCap", () => { t.captain = id; save(t); closePlayer(); render(); flash(id); toast(`CAP: ${sur(r.name)}`); });
    on("aSwap", () => {
      const others = rows.filter((x) => x.id !== id && x.position !== "Head Coach" && (t.roles || {})[x.id] !== role);
      sheet(`<div class="sh"><div><h2>${esc(sur(r.name))} ⇄ …</h2><div class="muted">${L("Τώρα", "Now")}: ${esc(ROLE_LABEL[role] || role)}</div></div>
          <button class="x" aria-label="${L("Κλείσιμο", "Close")}" onclick="closePlayer()">×</button></div>
        <div class="tm-acts">${others.map((x) => `<button class="tm-act" data-q="${x.id}"><span>${LETTER[x.position]}</span><div>${esc(nm(x.name))}
          <small>${esc(ROLE_LABEL[(t.roles || {})[x.id]] || (t.roles || {})[x.id] || "")} · ${scored(x) ? `${L("έφερε", "scored")} ${f1(pts(x))}` : `xFPT ${f1(x.x_now)}`}</small></div></button>`).join("")}</div>`);
      document.querySelectorAll("#sheet [data-q]").forEach((b) => b.onclick = () => { if (swap(t, id, Number(b.dataset.q))) closePlayer(); });
    });
    on("aRep", () => replaceSheet(t, r));
    on("aOut", () => { if (sellOut(t, id)) { closePlayer(); render(); } });
    on("aPrice", () => {
      sheet(`<div class="sh"><div><h2>${L("Price αγοράς", "Purchase price")}: ${esc(sur(r.name))}</h2><div class="muted">${L("Όσο τον πλήρωσες στο παιχνίδι · σημερινό price", "What you paid in the game · today's price")} ${f1(r.price)} cr</div></div>
          <button class="x" aria-label="${L("Κλείσιμο", "Close")}" onclick="closePlayer()">×</button></div>
        <input id="tmPrice" class="tm-input" inputmode="decimal" value="${f1(r.buy ?? r.price)}" autocomplete="off">
        <button class="tm-primary" id="tmPriceOk">${L("Αποθήκευση", "Save")}</button>`);
      $("#tmPriceOk").onclick = () => {
        const v = parseFloat(String($("#tmPrice").value).replace(",", "."));
        if (isNaN(v) || v <= 0) { toast(L("Γράψε ένα price, π.χ. 7,5", "Enter a price, e.g. 7.5")); return; }
        t.players.find((x) => x.id === id).price = v; save(t); closePlayer(); render(); toast(`${sur(r.name)}: ${L("αγορά", "bought at")} ${f1(v)} cr`);
      };
    });
    // the player's analysis, stats, games and price under the actions (same as the players' popup)
    if (typeof playerBody === "function") {
      $("#sheet").insertAdjacentHTML("beforeend", `<div id="tmDetails" data-pid="${esc(r.person_id)}"><p class="muted">${L("Φόρτωση στατιστικών…", "Loading stats…")}</p></div>`);
      playerBody(r.person_id).then((html) => {
        const box = document.getElementById("tmDetails");
        if (!box || box.dataset.pid !== String(r.person_id)) return;   // closed or another player meanwhile
        box.innerHTML = html;
        if (typeof bindPriceChart === "function") bindPriceChart(box);
      });
    }
  }
  // the watchlist (index.html): those players first in the lists of who fits
  const watched = (p) => (typeof isWatched === "function" && isWatched(p.person_id) ? 1 : 0);
  function replaceSheet(t, r) {
    const max = (Number(t.bank) || 0) + Number(r.price || 0);
    const have = new Set(t.players.map((x) => x.id));
    // only the players the credits allow (sold at today's price), the biggest gain over the next 3 rounds first
    const list = P.players.filter((p) => p.position === r.position && p.fantasy_id != null && p.price != null
        && p.price <= max + 1e-9 && !have.has(p.fantasy_id))
      .sort((a, b) => watched(b) - watched(a) || (b.x_h ?? 0) - (a.x_h ?? 0));
    const gain = (p) => (p.x_h ?? 0) - (r.x_h ?? 0);
    const draw = (q) => {
      const k = key(q).trim();
      $("#tmList").innerHTML = list.filter((p) => !k || key(p.name).includes(k)).slice(0, 40).map((p) => `<button class="tm-pick" data-n="${p.fantasy_id}">
          <span>${watched(p) ? "★ " : ""}<b>${esc(nm(p.name))}</b>${typeof newb === "function" ? newb(p, false) : ""}</span><span class="tm-pv"><b class="${gain(p) > 0 ? "tm-up" : "tm-down"}">${gain(p) > 0 ? "+" : "−"}${f1(Math.abs(gain(p)))}</b><small>xFPT3</small></span>
          <span class="muted tm-pm">${esc(tc(p.team))} · ${f1(p.price)} cr · xFPT3 ${f1(xf3(p))} · ${L("μένουν", "left")} ${f1(max - p.price)} cr</span></button>`).join("")
        || `<p class="muted">${k ? L(`Κανένας ${NAME[r.position]} με αυτό το όνομα μέσα στο υπόλοιπο.`, `No ${NAME[r.position]} with that name within your credits.`) : L(`Κανένας ${NAME[r.position]} δεν χωράει στο υπόλοιπο.`, `No ${NAME[r.position]} fits in your credits.`)}</p>`;
      document.querySelectorAll("#tmList [data-n]").forEach((b) => b.onclick = () => {
        const n = row(Number(b.dataset.n));
        applyTrade(t, r.id, n.fantasy_id, n.price); save(t); closePlayer(); render(); flash(n.fantasy_id);
        toast(`${sur(r.name)} ➜ ${sur(n.name)} · ${L("υπόλοιπο", "credits left")} ${f1(t.bank)} cr`);
      });
    };
    sheet(`<div class="sh"><div><h2>${L("Αντικατάσταση", "Replace")}: ${esc(sur(r.name))}</h2><div class="muted">${NAME[r.position]} · ${L(`${list.length} χωράνε στα ${f1(max)} cr · ★ watchlist και το μεγαλύτερο κέρδος σε xFPT3 πρώτα`, `${list.length} fit in ${f1(max)} cr · ★ watchlist and the biggest xFPT3 gain first`)}</div></div>
        <button class="x" aria-label="${L("Κλείσιμο", "Close")}" onclick="closePlayer()">×</button></div>
      <input id="tmQ" class="tm-input" placeholder="${L("Αναζήτηση", "Search")} ${NAME[r.position]}…" autocomplete="off"><div id="tmList"></div>`);
    draw(""); $("#tmQ").addEventListener("input", (e) => draw(e.target.value));
  }

  // ------------------------------------------------------------ ✕: take players off, then fill the empty places
  const sellLeft = (t) => { const ti = tradeInfo(t); return ti.max_trades > 4 ? Infinity : tradesLeft(t, ti); };
  function sellOut(t, id) {
    const out = sell ? sell.out : [];
    if (out.includes(id)) return false;
    if (out.length >= sellLeft(t)) { toast(sellLeft(t) ? L(`Σου μένουν ${sellLeft(t)} Trades`, `You have ${sellLeft(t)} Trades left`) : L("Δεν σου μένουν Trades", "You have no Trades left")); return false; }
    sell = { out: [...out, id], picks: sell ? sell.picks : {} };
    return true;
  }
  // credits as the game shows them while players are off: the sold at today's price, the picked paid
  function sellCredits(t) {
    const sold = sell.out.reduce((a, id) => a + (Number(row(id)?.price ?? t.players.find((x) => x.id === id)?.price) || 0), 0);
    const bought = Object.values(sell.picks).reduce((a, id) => a + (Number(row(id)?.price) || 0), 0);
    return Math.round(((Number(t.bank) || 0) + sold - bought) * 10) / 10;
  }
  function sellView(t) {
    const rows = rowsOf(t), roles = t.roles || {};
    const empty = sell.out.filter((id) => sell.picks[id] == null).length;
    const credits = sellCredits(t);
    const place = (r) => {
      if (!sell.out.includes(r.id)) return `<div class="chip tm-sellchip" data-off="${r.id}" role="button" tabindex="0" aria-label="✕ ${esc(nm(r.name))}">
          <span class="tm-x" aria-hidden="true">✕</span><div class="ct"><span>${LETTER[r.position]}</span><span>${esc(tc(r.team))}</span></div>
          <div class="cn">${esc(sur(r.name))}</div><div class="cp">${f1(r.price)}<small> cr</small></div></div>`;
      const n = sell.picks[r.id] != null ? row(sell.picks[r.id]) : null;
      return n ? `<div class="chip tm-sellchip tm-new" data-unpick="${r.id}" role="button" tabindex="0" aria-label="✕ ${esc(nm(n.name))}">
          <span class="tm-x" aria-hidden="true">✕</span><div class="ct"><span>${LETTER[n.position]}</span><span>${esc(tc(n.team))}</span></div>
          <div class="cn">${esc(sur(n.name))}</div><div class="cp">${f1(n.price)}<small> cr</small></div></div>`
        : `<button class="tm-slot" data-fill="${r.id}"><b>+</b>${NAME[r.position]}<small>${esc(sur(r.name))} ${f1(r.price)}</small></button>`;
    };
    const by = (role) => rows.filter((r) => (role === "coach" ? r.position === "Head Coach" : roles[r.id] === role && r.position !== "Head Coach"));
    const line = (pos) => by("5άδα").filter((r) => r.position === pos).map(place).join("");
    const ok = !empty && credits >= -0.05;
    return `<header class="tm-top"><div><h2 class="tm-h">Trades</h2>
        <div class="muted">${L("Πάτα ✕ σε όποιον φεύγει, μετά τις κενές θέσεις", "Tap ✕ on whoever goes, then the empty places")} · ${sell.out.length} ${sell.out.length === 1 ? "Trade" : "Trades"}${sellLeft(t) < Infinity ? ` · ${L("μένουν", "left")} ${sellLeft(t) - sell.out.length}` : ""}</div></div></header>
      <div class="card tm-courtcard"><div class="tm-floor"><div class="court tm-setcourt"><div class="crow">${line("Center")}</div><div class="crow">${line("Forward")}</div><div class="crow">${line("Guard")}</div></div>
        <div class="lanes"><div class="pair">
          <div class="lane six"><h3>Sixth man</h3><div class="crow">${by("6ος").map(place).join("")}</div></div>
          <div class="lane coach"><h3>Head Coach</h3><div class="crow">${by("coach").map(place).join("")}</div></div></div>
          <div class="lane bench"><h3>Bench (50% FPT)</h3><div class="crow">${by("πάγκος").map(place).join("")}</div></div></div></div>
        <div class="tm-money"><span>Credits <b class="${credits < -0.05 ? "tm-down" : ""}">${f1(credits)}</b> cr</span><span>${empty ? `${empty} ${empty === 1 ? L("κενή θέση", "empty place") : L("κενές θέσεις", "empty places")}` : L("πλήρης ομάδα", "full team")}</span></div>
        <button class="tm-primary" id="tmSellOk" ${ok ? "" : "disabled"}>${empty ? L(`Λείπουν ${empty}`, `${empty} missing`) : credits < -0.05 ? L(`Λείπουν ${f1(-credits)} cr`, `${f1(-credits)} cr short`) : L("Αποθήκευση ➜", "Save ➜")}</button>
        <button class="linkbtn" id="tmSellNo" style="display:block;margin:6px auto 0">${L("Άκυρο", "Cancel")}</button></div>`;
  }
  function fillSheet(t, outId, best) {
    const r = rowsOf(t).find((x) => x.id === outId);
    const taken = new Set([...t.players.map((x) => x.id), ...Object.values(sell.picks)]);
    const max = sellCredits(t);   // this place is empty, its player's credits are in already
    const list = P.players.filter((p) => p.position === r.position && p.fantasy_id != null && p.price != null
        && p.price <= max + 1e-9 && !taken.has(p.fantasy_id))
      .sort((a, b) => watched(b) - watched(a) || (b.x_h ?? 0) - (a.x_h ?? 0));
    const gain = (p) => (p.x_h ?? 0) - (r.x_h ?? 0);
    const draw = (q) => {
      const k = key(q).trim();
      $("#tmList").innerHTML = list.filter((p) => !k || key(p.name).includes(k)).slice(0, 40).map((p) => `<button class="tm-pick" data-n="${p.fantasy_id}">
          <span>${watched(p) ? "★ " : ""}<b>${esc(nm(p.name))}</b>${typeof newb === "function" ? newb(p, false) : ""}</span><span class="tm-pv"><b class="${gain(p) > 0 ? "tm-up" : "tm-down"}">${gain(p) > 0 ? "+" : "−"}${f1(Math.abs(gain(p)))}</b><small>xFPT3</small></span>
          <span class="muted tm-pm">${esc(tc(p.team))} · ${f1(p.price)} cr · xFPT3 ${f1(xf3(p))} · ${L("μένουν", "left")} ${f1(max - p.price)} cr</span></button>`).join("")
        || `<p class="muted">${k ? L(`Κανένας ${NAME[r.position]} με αυτό το όνομα μέσα στα credits.`, `No ${NAME[r.position]} with that name within the credits.`) : L(`Κανένας ${NAME[r.position]} δεν χωράει στα credits: πάτα ✕ σε άλλον παίκτη.`, `No ${NAME[r.position]} fits in the credits: tap ✕ on another player.`)}</p>`;
      document.querySelectorAll("#tmList [data-n]").forEach((b) => b.onclick = () => {
        sell.picks[outId] = Number(b.dataset.n); closePlayer(); render(best);
      });
    };
    sheet(`<div class="sh"><div><h2>${L(`Στη θέση του ${esc(sur(r.name))}`, `In place of ${esc(sur(r.name))}`)}</h2><div class="muted">${NAME[r.position]} · ${L(`${list.length} χωράνε στα ${f1(max)} cr · ★ watchlist και το μεγαλύτερο κέρδος σε xFPT3 πρώτα`, `${list.length} fit in ${f1(max)} cr · ★ watchlist and the biggest xFPT3 gain first`)}</div></div>
        <button class="x" aria-label="${L("Κλείσιμο", "Close")}" onclick="closePlayer()">×</button></div>
      <input id="tmQ" class="tm-input" placeholder="${L("Αναζήτηση", "Search")} ${NAME[r.position]}…" autocomplete="off"><div id="tmList"></div>`);
    draw(""); $("#tmQ").addEventListener("input", (e) => draw(e.target.value));
  }
  function bindSell(t, best) {
    const act = (el, fn) => { el.onclick = fn; el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } }; };
    document.querySelectorAll("#team [data-off]").forEach((c) => act(c, () => { if (sellOut(t, Number(c.dataset.off))) render(best); }));
    document.querySelectorAll("#team [data-unpick]").forEach((c) => act(c, () => { delete sell.picks[Number(c.dataset.unpick)]; render(best); }));
    document.querySelectorAll("#team [data-fill]").forEach((b) => b.onclick = () => fillSheet(t, Number(b.dataset.fill), best));
    $("#tmSellNo").onclick = () => { sell = null; render(best); };
    $("#tmSellOk").onclick = () => {
      if (sell.out.some((id) => sell.picks[id] == null) || sellCredits(t) < -0.05) return;
      const n = sell.out.length;
      for (const id of sell.out) { const p = row(sell.picks[id]); applyTrade(t, id, p.fantasy_id, p.price); }
      sell = null; save(t); render(best); window.scrollTo({ top: 0 });
      toast(`${n} ${n === 1 ? "Trade" : "Trades"} · ${L("υπόλοιπο", "credits left")} ${f1(t.bank)} cr`);
    };
  }

  // ------------------------------------------------------------ drag to swap (pointer events: touch + mouse)
  function bindCourt(t) {
    document.querySelectorAll("#team .chip[data-fid]").forEach((el) => {
      const id = Number(el.dataset.fid);
      const r = row(id);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); playerSheet(t, id); } });
      el.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        if (e.target.closest("[data-info]")) return;          // 🆕 and co. explain themselves (index.html), no drag or sheet
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

  // «Trades που μένουν»: the game counts every change of the round, the app only what it saw
  function leftSheet(t, best) {
    const ti = tradeInfo(t);
    sheet(`<div class="sh"><div><h2>${L("Trades που μένουν", "Trades left")}</h2><div class="muted">${L(`Όσα δείχνει το παιχνίδι για το Round ${ti.round}`, `As the game shows for Round ${ti.round}`)}</div></div>
        <button class="x" onclick="closePlayer()">×</button></div>
      <div class="tm-acts">${Array.from({ length: ti.max_trades + 1 }, (_, i) => ti.max_trades - i).map((v) =>
        `<button class="tm-act" data-left="${v}"><span>${v}</span><div>${v === 1 ? "1 Trade" : `${v} Trades`}${v === tradesLeft(t, ti) ? ` <small>${L("τώρα", "now")}</small>` : ""}</div></button>`).join("")}</div>`);
    document.querySelectorAll("#sheet [data-left]").forEach((b) => b.onclick = () => {
      setTradesLeft(t, Number(b.dataset.left)); save(t); closePlayer(); render(best);
      toast(L(`Μένουν ${b.dataset.left} Trades· οι προτάσεις προσαρμόστηκαν`, `${b.dataset.left} Trades left; the proposals adjusted`)); });
  }

  // ------------------------------------------------------------ menu
  // the toolbar: only ↶ (the last step, used often); «Undo all», «Save» and the trades left are in «⋯ Επιλογές»
  function undoBar(t) {
    const n = undoSteps(t);
    return `<div class="tm-toolbar" role="toolbar">${n ? `<button id="mUndoLast" title="Undo last" aria-label="Undo last"><span class="tm-ico" aria-hidden="true">↶</span><span class="tm-lbl">Undo</span></button>` : ""}</div>`;
  }
  const canUndoAll = (t) => undoSteps(t) > 1 || canUndo(t, P.trade_info || {});
  function bindUndo(t, best) {
    const last = () => { if (undoLast(t)) { render(best); toast(`${L("Αναιρέθηκε η τελευταία κίνηση", "Last move undone")}${undoSteps(t) ? ` · ${L("μένουν", "left")} ${undoSteps(t)}` : ""}`); } };
    if ($("#mUndoLast")) $("#mUndoLast").onclick = last;
    if ($("#tmBankEdit")) $("#tmBankEdit").onclick = () => bankSheet(t, best);
  }
  function askUndoAll(t, best) {
      const n = usedTrades(t, P.trade_info || {}), snap = !!(t.used && t.used.before);
      sheet(`<div class="sh"><h2>${L(`Αναίρεση ${n === 0 ? "των κινήσεων" : n === 1 ? "του Trade" : `των ${n} Trades`};`, `Undo ${n === 0 ? "the moves" : n === 1 ? "the Trade" : `the ${n} Trades`}?`)}</h2><button class="x" onclick="closePlayer()">×</button></div>
        <p class="muted">${snap || undoSteps(t) ? L("Η ομάδα, το υπόλοιπο, οι θέσεις και ο Captain γυρίζουν όπως ήταν στο τελευταίο κλείδωμα.", "The team, credits, positions and Captain go back to how they were at the last lock.")
          : L("Δεν υπάρχει αποθηκευμένη η ομάδα της αρχής του Round, οπότε μηδενίζεται μόνο ο μετρητής· τους παίκτες τους αλλάζεις από την «Αλλαγή ομάδας».", "The team from the start of the Round isn't saved, so only the counter resets; change the players with “Edit team”.")}</p>
        <button class="tm-primary" id="tmUndoOk">${L("Αναίρεση", "Undo")}</button>`);
      $("#tmUndoOk").onclick = () => { const ok = undoAll(t) || (undoTrades(t), save(t), !!snap); closePlayer(); render(best);
        toast(ok ? L("Η ομάδα γύρισε όπως ήταν", "The team is back as it was") : L("Ο μετρητής μηδενίστηκε", "The counter was reset")); };
  }

  // Credits ✎: the first number under CREDITS in the game
  function bankSheet(t, best) {
    sheet(`<div class="sh"><div><h2>Credits</h2><div class="muted">${L("Το πρώτο νούμερο στο CREDITS του παιχνιδιού", "The first number under CREDITS in the game")}</div></div>
        <button class="x" onclick="closePlayer()">×</button></div>
      <input id="tmBank" class="tm-input" inputmode="decimal" value="${f1(t.bank)}" autocomplete="off"><button class="tm-primary" id="tmBankOk">${L("Αποθήκευση", "Save")}</button>`);
    $("#tmBankOk").onclick = () => { const v = parseFloat(String($("#tmBank").value).replace(",", "."));
      if (isNaN(v) || v < 0) { toast(L("Γράψε ένα ποσό, π.χ. 3,5", "Enter an amount, e.g. 3.5")); return; }
      t.bank = v; save(t); closePlayer(); render(best); };
  }
  function cpSheet(t, best) {
    sheet(`<div class="sh"><div><h2>Save</h2><div class="muted">${L("Η ομάδα όπως είναι τώρα", "The team as it is now")}</div></div>
        <button class="x" onclick="closePlayer()">×</button></div>
      <p class="muted">${L(`Το «Undo all» θα γυρίζει την ομάδα εδώ, όχι πιο πίσω: π.χ. αν πέρασες τώρα Trades του προηγούμενου Round,
        δεν θα αναιρούνται μαζί με τα τωρινά. Ο μετρητής «Trades» μένει όπως είναι· αν χρειάζεται, διόρθωσέ τον με το ✎.`, `“Undo all” will bring the team back here, not further: e.g. if you just entered last Round's Trades,
        they won't be undone with the current ones. The “Trades” counter stays as it is; if needed, correct it in the menu.`)}</p>
      <button class="tm-primary" id="tmCpOk">${ico("save")} Save</button>`);
    $("#tmCpOk").onclick = () => { checkpoint(t); closePlayer(); render(best); toast(L("Saved · το «Undo all» γυρίζει πλέον εδώ", "Saved · “Undo all” now comes back here")); };
  }

  // the team's options: a dropdown behind «⋯ Επιλογές» (phones and wide screens alike)
  function menu(t, best) {
    const host = $("#tmMenu");
    if (!host) return;
    const close = () => { host.innerHTML = ""; };
    if (host.innerHTML) { close(); return; }
    host.innerHTML = `<div class="tm-menu" role="menu">
      ${canUndoAll(t) ? `<button id="mUsed">↺ Undo all <small class="muted">${L("ως την αρχή του Round ή το Save", "back to the Round's start or the Save")}</small></button>` : ""}
      <button id="mCp">${ico("save")} Save <small class="muted">${L("εδώ θα γυρίζει το «Undo all»", "“Undo all” will come back here")}</small></button>
      ${(P.trade_info || {}).max_trades <= 4 ? `<button id="mTrades">${ico("edit")} ${L("Διόρθωση Trades", "Correct Trades")} <small class="muted">${L("πόσα σου μένουν", "how many you have left")}</small></button>` : ""}
      <button id="mSync">${ico("sync")} ${L("Συγχρονισμός συσκευών", "Sync devices")}${syncGet() ? `<span class="tm-on" title="${L("ενεργός", "on")}">✓</span>` : ""}</button>
      <button id="mBackup">${ico("link")} ${L("Αντίγραφο ασφαλείας", "Backup")}</button>
      <button id="mEdit">${ico("edit")} ${L("Αλλαγή ομάδας", "Edit team")}</button>
      ${WIDE() ? "" : `<button id="mInstall">${ico("phone")} ${L("Βάλ' το στην οθόνη σου", "Add to home screen")}</button>`}
      <button id="mMail">${ico("mail")} ${L("Επικοινωνία", "Contact")}</button>
      <button id="mDel" class="tm-danger">${ico("trash")} ${L("Διαγραφή ομάδας", "Delete team")}</button></div>`;
    $("#mSync").onclick = () => { close(); syncSheet(() => render(best)); };
    if ($("#mUsed")) $("#mUsed").onclick = () => { close(); askUndoAll(t, best); };
    $("#mCp").onclick = () => { close(); cpSheet(t, best); };
    if ($("#mTrades")) $("#mTrades").onclick = () => { close(); leftSheet(t, best); };
    $("#mBackup").onclick = async () => {
      close();
      const link = location.origin + location.pathname + "#t=" + encode(t);
      try { await navigator.clipboard.writeText(link); toast(L("Ο σύνδεσμος αντιγράφηκε — κράτα τον π.χ. στις σημειώσεις", "Link copied — keep it e.g. in your notes")); }
      catch (e) { sheet(`<div class="sh"><h2>${L("Σύνδεσμος ομάδας", "Team link")}</h2><button class="x" onclick="closePlayer()">×</button></div>
        <p class="muted">${L("Αντίγραψε και κράτα τον. Ανοίγοντάς τον σε άλλη συσκευή επανέρχεται η ομάδα σου.", "Copy and keep it. Opening it on another device restores your team.")}</p>
        <textarea class="tm-input" rows="4" readonly onclick="this.select()">${esc(link)}</textarea>`); }
    };
    $("#mEdit").onclick = () => { close(); setup = { players: t.players.map((x) => ({ ...x })) }; mode = "setup"; render(best); };
    $("#mMail").onclick = () => { close();             // copied (no mail app on the phone?) and the mail opens
      copyText(FEEDBACK_MAIL).then((ok) => toast(ok ? `${L("Αντιγράφηκε", "Copied")}: ${FEEDBACK_MAIL}` : FEEDBACK_MAIL));
      location.href = `mailto:${FEEDBACK_MAIL}?subject=${encodeURIComponent("Coach Dime beta")}`; };
    if ($("#mInstall")) $("#mInstall").onclick = () => { close(); installGuide(true); };
    $("#mDel").onclick = () => {
      close();
      sheet(`<div class="sh"><h2>${L("Διαγραφή της ομάδας από αυτή τη συσκευή;", "Delete the team from this device?")}</h2><button class="x" onclick="closePlayer()">×</button></div>
        <p class="muted">${L("Αν έχεις κρατήσει σύνδεσμο αντιγράφου, μπορείς να την επαναφέρεις αργότερα.", "If you kept a backup link, you can restore it later.")}</p>
        <button class="tm-primary tm-danger-bg" id="tmDelOk">${L("Διαγραφή", "Delete")}</button>`);
      $("#tmDelOk").onclick = () => { try { localStorage.removeItem(KEY); } catch (e) {} syncSet(null); closePlayer(); setup = null; mode = null; render(best); };
    };
  }
  document.addEventListener("click", (e) => { if (!e.target.closest("#tmMenu, #tmMore")) { const h = document.getElementById("tmMenu"); if (h) h.innerHTML = ""; } });

  // ------------------------------------------------------------ setup on an empty court
  function setupView(best) {
    const ps = setup.players.map((x) => ({ ...x, r: row(x.id) })).filter((x) => x.r);
    const have = (pos) => ps.filter((x) => x.r.position === pos);
    const spent = ps.reduce((a, x) => a + (Number(x.price) || 0), 0);
    const full = Object.entries(NEED).every(([pos, n]) => have(pos).length === n);
    const slots = (pos) => have(pos).map((x) => `<div class="chip tm-setchip" data-set="${x.id}" role="button" tabindex="0" title="${L("price ή αφαίρεση", "price or remove")}">
        <div class="ct"><span>${LETTER[pos]}</span><span>${esc(tc(x.r.team))}</span></div><div class="cn">${esc(sur(x.r.name))}</div>
        <div class="cp">${f1(x.price)}<small> cr</small></div></div>`).join("")
      + Array.from({ length: NEED[pos] - have(pos).length }, () => `<button class="tm-slot" data-pos="${pos}"><b>+</b>${NAME[pos]}</button>`).join("");
    const had = !!load();
    return `<header class="tm-top"><div><h2 class="tm-h">${had ? L("Αλλαγή ομάδας", "Edit team") : L("Φτιάξε την ομάδα σου", "Build your team")}</h2>
        <div class="muted">${L("Πάτα μια κενή θέση και διάλεξε παίκτη · πάτα έναν παίκτη για να γράψεις το price αγοράς του ή να τον αφαιρέσεις", "Tap an empty place and pick a player · tap a player to enter his purchase price or remove him")} · ${ps.length}/11</div></div></header>
      ${!had && !ps.length && best?.team?.length ? `<div class="tm-start"><button class="tm-primary" id="tmStartBest" type="button">${L("Ξεκίνα από την προτεινόμενη ομάδα", "Start from the proposed team")}</button>
          <p class="tm-hint">${L("Μπαίνουν οι 11 της πρότασης με τα σημερινά prices. Μετά πάτα όσους δεν έχεις, «Αφαίρεση», και βάλε τους δικούς σου.", "The proposal's 11 go in at today's prices. Then tap the ones you don't have, “Remove”, and add your own.")}</p>
          <p class="muted tm-or">${L("ή πάτα τις κενές θέσεις και διάλεξε έναν έναν", "or tap the empty places and pick one by one")}</p></div>` : ""}
      <div class="card tm-courtcard"><div class="tm-floor"><div class="court tm-setcourt">
          <div class="crow">${slots("Center")}</div><div class="crow">${slots("Forward")}</div><div class="crow">${slots("Guard")}</div></div>
        <div class="lanes">
          <div class="lane coach"><h3>Head Coach · ${have("Head Coach").length}/1</h3><div class="crow">${slots("Head Coach")}</div></div></div></div>
        <div class="tm-money"><span>${L("Κόστος ομάδας", "Team cost")} <b>${f1(spent)}</b> cr</span><span>Credits <b>${f1(Math.max(0, 100 - spent))}/100</b></span></div>
        ${spent > 100.05 ? `<p class="tm-over">${ico("warn")} ${L(`Πάνω από το budget κατά <b>${f1(spent - 100)}</b> cr — έλεγξε τα prices (πάτα τον παίκτη)· το παιχνίδι δεν επιτρέπει πάνω από 100.`, `Over budget by <b>${f1(spent - 100)}</b> cr — check the prices (tap the player); the game doesn't allow more than 100.`)}</p>` : ""}
        <button class="tm-primary" id="tmFinish" ${full ? "" : "disabled"}${!had && !ps.length && best?.team?.length ? " hidden" : ""}>${full ? L("Αποθήκευση ➜", "Save ➜") : L(`Λείπουν ${11 - ps.length}`, `${11 - ps.length} missing`)}</button>
        ${had ? `<button class="linkbtn" id="tmCancel" style="display:block;margin:6px auto 0">${L("Άκυρο", "Cancel")}</button>` : ""}
        <p class="tm-hint">${L("Γράψε τα prices <b>αγοράς</b> (όσο πλήρωσες τον καθένα)· συμπληρώνονται με τα σημερινά, αν διαφέρουν πάτα τον παίκτη. Έτσι βλέπεις πόσο ανέβηκαν ή έπεσαν· στα Trades μετράει το σημερινό price. Το υπόλοιπο το διορθώνεις από τις «Επιλογές».", "Enter the <b>purchase</b> prices (what you paid for each); they are filled with today's, tap the player if they differ. That way you see how much they rose or fell; Trades use today's price. Correct your credits from the header.")}</p>
        ${had ? "" : `<button class="linkbtn" id="tmRestore" style="display:block;margin:8px auto 0">${L("Σύνδεσμος αντιγράφου", "Backup link")}</button>`
          + `<button class="linkbtn" id="tmSyncSetup" style="display:block;margin:4px auto 0">${L("Κωδικός συγχρονισμού", "Sync code")}</button>`}</div>`;
  }
  // setting up: a picked player's price (as in your game) or removing him
  function setupPlayerSheet(id, best) {
    const x = setup.players.find((q) => q.id === id), r = row(id);
    if (!x || !r) return;
    sheet(`<div class="sh"><div><h2>${esc(nm(r.name))}</h2><div class="muted">${esc(tc(r.team))} · ${NAME[r.position]} · ${L("σημερινό price", "today's price")} ${f1(r.price)} cr</div></div>
        <button class="x" aria-label="${L("Κλείσιμο", "Close")}" onclick="closePlayer()">×</button></div>
      <label class="muted" for="tmSetPrice">${L("Price αγοράς: όσο τον πλήρωσες στο παιχνίδι", "Purchase price: what you paid in the game")}</label>
      <input id="tmSetPrice" class="tm-input" inputmode="decimal" value="${f1(x.price)}" autocomplete="off">
      <button class="tm-primary" id="tmSetOk">${L("Αποθήκευση price αγοράς", "Save purchase price")}</button>
      <button class="tm-primary tm-danger-bg" id="tmSetRm" style="margin-top:8px">${L("Αφαίρεση από την ομάδα", "Remove from the team")}</button>`);
    setTimeout(() => $("#tmSetPrice")?.select(), 50);
    const ok = () => {
      const v = parseFloat(String($("#tmSetPrice").value).replace(",", "."));
      if (isNaN(v) || v <= 0 || v > 40) { toast(L("Γράψε ένα price, π.χ. 7,5", "Enter a price, e.g. 7.5")); return; }
      x.price = Math.round(v * 10) / 10; closePlayer(); render(best);
    };
    $("#tmSetOk").onclick = ok;
    $("#tmSetPrice").onkeydown = (e) => { if (e.key === "Enter") ok(); };
    $("#tmSetRm").onclick = () => { setup.players = setup.players.filter((q) => q.id !== id); closePlayer(); render(best); };
  }
  function pickSheet(pos, best) {
    const have = new Set(setup.players.map((x) => x.id));
    const list = P.players.filter((p) => p.position === pos && p.fantasy_id != null && p.price != null && !have.has(p.fantasy_id))
      .sort((a, b) => (b.price ?? 0) - (a.price ?? 0));
    const draw = (q) => {
      const k = key(q).trim();
      $("#tmList").innerHTML = list.filter((p) => !k || key(p.name).includes(k)).slice(0, 60).map((p) => `<button class="tm-pick" data-p="${p.fantasy_id}">
          <span><b>${esc(nm(p.name))}</b></span><span class="tm-pv"><b>${f1(p.price)}</b><small>cr</small></span>
          <span class="muted tm-pm">${esc(tc(p.team))} · xFPT ${f1(p.x_now)}</span></button>`).join("") || `<p class="muted">${L(`Κανένας ${NAME[pos]} με αυτό το όνομα.`, `No ${NAME[pos]} with that name.`)}</p>`;
      document.querySelectorAll("#tmList [data-p]").forEach((b) => b.onclick = () => {
        const r = row(Number(b.dataset.p)); setup.players.push({ id: r.fantasy_id, price: r.price }); closePlayer(); render(best);
      });
    };
    sheet(`<div class="sh"><div><h2>${L("Διάλεξε", "Pick a")} ${NAME[pos]}</h2><div class="muted">${L("Γράψε μερικά γράμματα του ονόματος", "Type a few letters of the name")}</div></div>
        <button class="x" aria-label="${L("Κλείσιμο", "Close")}" onclick="closePlayer()">×</button></div>
      <input id="tmQ" class="tm-input" placeholder="${L("Αναζήτηση", "Search")} ${NAME[pos]}…" autocomplete="off"><div id="tmList"></div>`);
    draw(""); if (matchMedia("(hover: hover)").matches) setTimeout(() => $("#tmQ")?.focus(), 50);   // not on phones: the keyboard would jump up
    $("#tmQ").addEventListener("input", (e) => draw(e.target.value));
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
    // «Αλλαγή ομάδας» after trades: the count starts again (nothing here is binding), but the team as it was
    // at the start of the round stays, so «Αναίρεση» still brings it back
    const ti = P.trade_info || { round: P.round };
    if (old && roundStart(old, ti)) t.used = { round: ti.round, n: 0, before: old.used.before };
    save(t); setup = null; mode = null;
  }

  // ------------------------------------------------------------ render
  function bestCard(best) {
    if (!best) return "";
    // same sideline layout as «Your Starting five» on a PC (head coach and 6th left, bench right)
    return `<details class="card"><summary><b>${L("Καλύτερη ομάδα του Round (xFPT)", "Best team of the Round (xFPT)")}</b> <span class="muted">· ${f1(best.cost)} cr</span></summary>
      <div class="tm-sideline">${courtView(best.team.map((p) => ({ ...p, actual: null })), null)}</div></details>`;
  }
  let pulled = false;
  function render(best) {
    best = best === undefined ? P.best_team : best;
    // the other device's changes: once per page load (and on coming back to it, above)
    onRemote = () => render(best);
    if (!pulled && !GAME()) { pulled = true; syncPull(); }
    if (GAME()) {
      const g = myTeam();
      if (!g) { $("#team").innerHTML = `<div class="card warn"><h2>${L("Η ομάδα δεν είναι διαθέσιμη", "The team isn't available")}</h2>
        <p>${L("Χρειάζεται έγκυρο <code>FANTASY_TOKEN</code> στα GitHub Secrets.", "Needs a valid <code>FANTASY_TOKEN</code> in the GitHub Secrets.")}</p></div>${bestCard(best)}`; return; }
      if (sell && sell.out.every((id) => g.players.some((x) => x.id === id))) {
        $("#team").innerHTML = sellView(g); sizeFloors(); bindSell(g, best); return;
      }
      sell = null;
      const y = window.scrollY;
      $("#team").innerHTML = mainView(g, best);
      if (Math.abs(window.scrollY - y) > 2) window.scrollTo({ top: y });
      bindTrades(g, best);
      const x = document.getElementById("tmDraftX");
      if (x) x.onclick = () => { dropDraft(); render(best); toast(L("Η ομάδα γύρισε όπως είναι στο παιχνίδι", "The team is back as it is in the game")); };
      bindKeep(g, best);
      bindSteps();
      document.querySelectorAll("#team .chip[data-fid]").forEach((el) => el.onclick = (e) => {
        if (e.target.closest("[data-info]")) return;
        playerSheet(g, Number(el.dataset.fid));
      });
      return;
    }
    const t = load();
    if (mode === "setup" || !t) {
      if (!setup) setup = { players: [] };
      mode = "setup";
      $("#team").innerHTML = setupView(best); sizeFloors();
      // a new user starts from the proposal (the best team for 100 credits) and swaps in the players he has
      const sb = document.getElementById("tmStartBest");
      if (sb) sb.onclick = () => {
        setup.players = best.team.map((p) => ({ id: p.id, price: row(p.id)?.price ?? p.price })).filter((x) => row(x.id));
        render(best); toast(L("Η προτεινόμενη ομάδα μπήκε· άλλαξε όσους δεν έχεις", "The proposed team is in; swap the ones you don't have"));
      };
      document.querySelectorAll("#team .tm-slot").forEach((b) => b.onclick = () => pickSheet(b.dataset.pos, best));
      document.querySelectorAll("#team [data-set]").forEach((c) => {
        const open = () => setupPlayerSheet(Number(c.dataset.set), best);
        c.onclick = open;
        c.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
      });
      const fin = document.getElementById("tmFinish");
      if (fin) fin.onclick = () => { finishSetup(); render(best); window.scrollTo({ top: 0 }); toast(L("Η ομάδα αποθηκεύτηκε", "Team saved")); };
      const ss = document.getElementById("tmSyncSetup");
      if (ss) ss.onclick = () => syncSheet(() => render(best));
      const rest = document.getElementById("tmRestore");
      if (rest) rest.onclick = () => restoreSheet(() => render(best));
      const cancel = document.getElementById("tmCancel");
      if (cancel) cancel.onclick = () => { setup = null; mode = null; render(best); };
      return;
    }
    if (!t.roles || Object.keys(t.roles).length !== t.players.length) {   // e.g. an old backup link: start from the proposal
      const res = ELFOPT.lineup(optRows(rowsOf(t), t, false));
      if (res) { t.roles = Object.fromEntries(res.team.map((p) => [p.id, p.role])); t.captain = res.team.find((p) => p.captain)?.id ?? null; t.confirmed = false; save(t); }
    }
    if (sell && sell.out.every((id) => t.players.some((x) => x.id === id))) {
      $("#team").innerHTML = sellView(t); sizeFloors(); bindSell(t, best); return;
    }
    sell = null;
    const pl = mainView(t, best), y = window.scrollY;
    $("#team").innerHTML = pl;
    if (Math.abs(window.scrollY - y) > 2) window.scrollTo({ top: y });   // a change doesn't throw you to the top
    bindTrades(t, best);
    const on = (i, fn) => { const el = document.getElementById(i); if (el) el.onclick = fn; };
    on("tmConfirm", () => { t.confirmed = true; save(t); render(best); });
    on("tmMore", (e) => { e.stopPropagation(); menu(t, best); });
    bindUndo(t, best);
    on("tmEdit", () => { setup = { players: t.players.map((x) => ({ ...x })) }; mode = "setup"; render(best); });
    bindKeep(t, best);
    bindSteps();
    bindCourt(t);
  }
  // «✓ Το έκανα» on the steps and the trades, and the trades left (both editions)
  function bindTrades(t, best) {
    const p = plan(t);   // cached trades: cheap
    document.querySelectorAll("#team .tm-done[data-i]").forEach((b) => b.onclick = () => {
      const it = p.items[Number(b.dataset.i)]; if (!it) return;
      it.run(); render(best);
    });
    document.querySelectorAll("#team .tm-done[data-n]").forEach((b) => b.onclick = () => {
      const pr = p.trs.pairs[Number(b.dataset.n)];
      applyTrade(t, pr.out.id, pr.in.id, pr.in.price); save(t); render(best); toast(`${L("Έγινε", "Done")} · ${L("υπόλοιπο", "credits left")} ${f1(t.bank)} cr`);
    });
    const lp = document.getElementById("tmLeft");
    if (lp) lp.onchange = () => { setTradesLeft(t, Number(lp.value)); save(t); render(best);
      toast(L(`Μένουν ${lp.value} Trades· οι προτάσεις προσαρμόστηκαν`, `${lp.value} Trades left; the proposals adjusted`)); };
    const tr = document.getElementById("tmTrades");
    if (tr) tr.onclick = () => leftSheet(t, best);
  }
  // PC: the side columns (coach, 6th, bench) start level with the top of the court; they are placed from the
  // row under the court, so they are lifted by the court's height (the centre circle stays where it is)
  // measured when the court gets its size, not only at render: a court drawn on a hidden tab, or before
  // the fonts load, has no height yet (the columns then started at the bottom of the court)
  const floorObs = typeof ResizeObserver === "function" ? new ResizeObserver((es) => {
    for (const e of es) { const f = e.target.closest(".tm-floor"); if (f && e.target.offsetHeight) f.style.setProperty("--court-h", e.target.offsetHeight + "px"); }
  }) : null;
  function sizeFloors() {
    document.querySelectorAll(".tm-floor").forEach((f) => {
      const c = f.querySelector(".court");
      if (!c) return;
      if (c.offsetHeight) f.style.setProperty("--court-h", c.offsetHeight + "px");
      if (floorObs && !c.dataset.obs) { c.dataset.obs = "1"; floorObs.observe(c); }
    });
  }
  window.addEventListener("resize", sizeFloors);
  document.addEventListener("toggle", sizeFloors, true);      // the best-team card opens
  // phones: the court comes first, this line says there are steps to do below it and takes you there
  function bindSteps() {
    sizeFloors();
    document.querySelectorAll("#team li[data-cmp]").forEach((li) => li.onclick = (e) => {
      if (e.target.closest("button")) return;
      if (typeof compareSheet === "function") compareSheet(li.dataset.cmp.split(","));
    });
    const all = document.querySelector("#team .tm-all");
    if (all) all.ontoggle = () => { allSteps = all.open; };
    const b = document.getElementById("tmSteps"), to = document.getElementById("tmTodo");
    // the line counts all the steps, so it opens the folded ones too (and the page is then long enough to get there)
    if (b && to) b.onclick = () => { if (all) all.open = allSteps = true;
      window.scrollTo({ top: to.getBoundingClientRect().top + window.scrollY - 8, behavior: "smooth" }); };
  }
  // «Δεν θέλω να διώξω αυτόν τον παίκτη αυτό το Round» and its undo: re-plan the trades
  function bindKeep(t, best) {
    const ti = tradeInfo(t);
    document.querySelectorAll("#team [data-keep]").forEach((b) => b.onclick = () => {
      const id = Number(b.dataset.keep), r = row(id);
      setKept(ti, [...new Set([...kept(ti), id])]); render(best);
      toast(L(`Κρατάς τον ${sur(r ? r.name : "")} — νέες προτάσεις`, `Keeping ${sur(r ? r.name : "")} — new proposals`));
    });
    document.querySelectorAll("#team [data-unkeep]").forEach((b) => b.onclick = () => {
      setKept(ti, kept(ti).filter((x) => x !== Number(b.dataset.unkeep))); render(best);
    });
    document.querySelectorAll("#team [data-avoid]").forEach((b) => b.onclick = () => {
      const id = Number(b.dataset.avoid), r = row(id);
      setAvoided(ti, [...new Set([...avoided(ti), id])]); render(best);
      toast(L(`Χωρίς τον ${sur(r ? r.name : "")} — νέες προτάσεις`, `Without ${sur(r ? r.name : "")} — new proposals`));
    });
    document.querySelectorAll("#team [data-unavoid]").forEach((b) => b.onclick = () => {
      setAvoided(ti, avoided(ti).filter((x) => x !== Number(b.dataset.unavoid))); render(best);
    });
  }

  // styles for this screen
  const css = document.createElement("style");
  css.textContent = `
  .tm-steps { display: none; }   /* phones only (below) */
  .tm-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin: 2px 0 12px; }
  /* not the page's header: it scrolls with the page (the global header rule made it sticky and covered the court); above the court for the options menu */
  #team header.tm-top { position: relative; z-index: 3; background: none; border: 0; padding: 0; transform: none; transition: none; }
  .tm-h { font-size: 20px; margin: 0; }
  .tm-dead { display: inline-block; font-size: 12px; font-weight: 600; color: var(--accent); margin-top: 4px;
    background: color-mix(in srgb, var(--accent) 12%, transparent); border-radius: 999px; padding: 2px 9px; }
  .tm-morewrap { position: relative; }
  .tm-more { border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary); border-radius: 999px;
    padding: 8px 14px; font: inherit; font-size: 14px; font-weight: 600; white-space: nowrap; cursor: pointer; }
  .tm-toolbar { display: flex; flex-wrap: wrap; gap: 8px; }
  /* wraps on the narrowest phones: Undo, Undo all and ⋯ Επιλογές in one row overflowed 320px (the page got wider) */
  .tm-right { display: flex; gap: 6px; align-items: flex-start; flex-wrap: wrap; justify-content: flex-end; flex: 0 1 auto; min-width: 0; }
  .tm-top > div:first-child { min-width: 0; }
  .tm-toolbar button { border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary); border-radius: 999px;
    padding: 7px 13px; font: inherit; font-size: 14px; cursor: pointer; }
  .tm-toolbar button:hover { border-color: var(--series-1); }
  .tm-toolbar button { touch-action: manipulation; }   /* iPhone: no wait for a double-tap zoom */
  .tm-menu { position: absolute; right: 0; top: 44px; z-index: 5; background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 12px; box-shadow: 0 6px 20px rgba(0,0,0,.15); min-width: 230px; overflow: hidden; }
  .tm-menu button, .tm-menu a { box-sizing: border-box; text-decoration: none; }
  .tm-menu button, .tm-menu a { white-space: nowrap; }   /* the ✓ of «Συγχρονισμός» stays on its line */
  .tm-menu .tm-on { color: var(--good); font-weight: 700; margin-left: 6px; }
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
  .tm-item .tm-done { padding: 7px 10px; }
  @media (max-width: 340px) {   /* the narrowest phones: the button goes under the text, which keeps the full width */
    .tm-item { grid-template-columns: 30px 1fr; } .tm-item .tm-done { grid-column: 2; justify-self: start; } }
  .tm-code { font: 700 24px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .06em; text-align: center; margin: 4px 0 12px; }
  .tm-sep { border: 0; border-top: 1px solid var(--border); margin: 14px 0; }
  .tm-live { margin: 0 0 10px; padding: 10px 12px; border-radius: 10px; font-size: 14px;
    background: color-mix(in srgb, var(--accent) 12%, transparent); }
  .tm-ready { padding: 12px; border-radius: 12px; font-weight: 600; background: color-mix(in srgb, var(--good) 14%, transparent); }
  .tm-hint { color: var(--text-muted); font-size: 12px; margin: 8px 2px 0; }
  .tm-acts { display: grid; gap: 8px; margin-top: 12px; }
  .tm-act { display: flex; gap: 10px; align-items: center; width: 100%; text-align: left; border: 1px solid var(--border);
    background: var(--surface-1); color: var(--text-primary); border-radius: 12px; padding: 12px; cursor: pointer; font: inherit; }
  .tm-act > span { width: 24px; text-align: center; font-size: 17px; }
  .tm-act small { display: block; color: var(--text-muted); font-size: 12px; }
  .tm-act:disabled { opacity: .45; cursor: default; }
  /* the whole squad stands on the court: the five in the half with the basket, 6th/coach/bench past the half-court line */
  /* parquet: index.html. At most 540px wide: the lines are drawn to the width, so a wide, low court (the set-up on a PC)
     would blow up the key and the circle and cut the three-point line */
  .tm-floor { position: relative; border: 2px solid rgba(255,255,255,.55); border-radius: 12px; overflow: hidden; padding-bottom: 8px;
    max-width: 540px; margin-left: auto; margin-right: auto; }
  .tm-floor .court { background: transparent; border: 0; border-bottom: 2px solid var(--court-line); border-radius: 0; overflow: visible; }
  .tm-floor .lanes { position: relative; margin-top: 0; padding: calc(12% + 12px) 8px 0; }   /* below the centre circle */
  /* the centre circle, whole, on the half-court line (FIBA: 3.6 m of the 15 m width) */
  .tm-floor .lanes::before { content: ""; position: absolute; left: 50%; top: -1px; width: 24%; aspect-ratio: 1; transform: translate(-50%, -50%);
    border: 2px solid var(--court-line); border-radius: 50%; background: var(--court-key); }
  .tm-floor .lanes > * { position: relative; z-index: 1; }
  /* room beside the court (PC, tablet): the head coach and the 6th stand on the sideline, left of the floor,
     so the court card is shorter and the whole squad fits without scrolling. Phones keep them on the floor. */
  :is(.tm-courtcard, .tm-sideline) { container-type: inline-size; }
  @container (min-width: 500px) {
    :is(.tm-courtcard, .tm-sideline) .tm-floor { overflow: visible; margin-left: 132px; margin-right: auto; }
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lanes .pair { display: block; }
    /* placed from the row under the court (.lanes), lifted by the court's height (--court-h, set in sizeFloors) */
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lanes .pair { position: static; }
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.coach, :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.six { position: absolute; left: -132px; width: 120px; margin: 0; }
    /* anchored to the top of the floor, stacked downwards: the coach, then the 6th below him */
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.coach { top: calc(8px - var(--court-h, 0px)); }
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.six { top: calc(150px - var(--court-h, 0px)); }
    :is(.tm-courtcard, .tm-sideline) .tm-floor:not(:has(.lane.coach)) .lane.six { top: calc(8px - var(--court-h, 0px)); }
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.coach .chip, :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.six .chip { width: 100%; max-width: none; }
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.coach h3, :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.six h3 { color: var(--text-secondary) !important; opacity: 1; }
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.coach .tm-slot { width: 100%; max-width: none; border-color: var(--text-muted); color: var(--text-secondary);
      background: var(--surface-0); }
  }
  /* more room (a PC): the bench on the right sideline, the four stacked, so the floor is only the court */
  @container (min-width: 580px) {
    :is(.tm-courtcard, .tm-sideline) .tm-floor { margin-right: 132px; }
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.bench { position: absolute; right: -132px; top: calc(8px - var(--court-h, 0px)); width: 120px; margin: 0; }
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.bench .crow { flex-direction: column; flex-wrap: nowrap; gap: 6px; }
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.bench .chip { width: 100%; max-width: none; }
    :is(.tm-courtcard, .tm-sideline) .tm-floor .lane.bench h3 { color: var(--text-secondary) !important; opacity: 1; }
  }
  /* set-up: the 4 forwards and 4 guards stand on the court too, four to a row */
  .tm-setcourt .crow > * { width: calc(25% - 5px); max-width: 128px; }
  .tm-setcourt .chip .cp { font-size: 17px; white-space: nowrap; } .tm-setcourt .chip .cp small { font-size: 11px; }
  .tm-setcourt .chip .ct span:last-child { font-size: 9px; }
  .tm-floor .lane h3 { color: var(--text-primary); opacity: .75; }
  /* phones: the court runs edge to edge */
  @media (max-width: 560px) {
    .tm-courtcard { margin-left: -16px; margin-right: -16px; border-radius: 0; border-left: 0; border-right: 0; padding-left: 0; padding-right: 0; }
    .tm-courtcard > h2, .tm-courtcard > .tm-hint, .tm-courtcard > .tm-money, .tm-courtcard > button, .tm-courtcard > p { margin-left: 14px; margin-right: 14px; }
    .tm-courtcard > .tm-primary { width: calc(100% - 28px); }
    .tm-courtcard .tm-floor { border-radius: 0; border-left: 0; border-right: 0; }
    /* «Η ομάδα μου»: the court first, then the to-do list; the whole squad in one screen (header hidden) */
    .tm-cols { display: flex; flex-direction: column; }
    .tm-cols > .tm-colR { order: -1; }
    .tm-cols .tm-steps { display: flex; align-items: center; gap: 6px; width: calc(100% + 32px); margin: 0 -16px 10px; padding: 9px 14px;
      border: 0; border-block: 1px solid color-mix(in srgb, var(--accent) 35%, transparent); background: color-mix(in srgb, var(--accent) 12%, var(--surface-1));
      color: var(--text-primary); font: inherit; font-size: 14px; text-align: left; cursor: pointer; }
    .tm-cols .tm-steps span { margin-left: auto; color: var(--accent); font-weight: 700; }
    .tm-cols .tm-courtcard > h2 { font-size: 15px; margin-bottom: 6px; } .tm-cols .tm-courtcard > h2 small { font-size: 11px; }
    .tm-cols .tm-floor .court.lined { aspect-ratio: 15 / 12; padding-top: 12px; padding-bottom: calc(12% + 4px); }
    .tm-cols .tm-floor .court.lined > .crow { margin-bottom: 4px; }
    .tm-cols .tm-floor .chip { padding: 3px 5px 4px; }
    .tm-cols .tm-floor .chip .ct { font-size: 9px; line-height: 12px; }
    .tm-cols .tm-floor .chip .cn { line-height: 1.2; }
    .tm-cols .tm-floor .chip .cp { font-size: 18px; line-height: 1.1; }
    .tm-cols .tm-floor .lanes { padding-top: calc(12% + 2px); gap: 4px; }
    .tm-cols .tm-floor .lane h3 { font-size: 11px; margin-bottom: 3px; }
    .tm-cols .tm-floor .lane.bench .crow { flex-wrap: nowrap; margin-bottom: 0; }
    .tm-cols .tm-floor .lane.bench .chip { width: calc(25% - 5px); }
    .tm-cols .tm-floor .pair .crow { margin-bottom: 0; }
    /* the 6th and the coach stand either side of the centre circle, the bench below it */
    .tm-cols .tm-floor .lanes { padding-top: 8px; grid-template-columns: minmax(0, 1fr); }
    .tm-cols .tm-floor .lanes .pair { grid-template-columns: minmax(0, 1fr) 26% minmax(0, 1fr); }
    .tm-cols .tm-floor .lanes .pair .lane.coach { grid-column: 3; }
    .tm-cols .tm-floor .lanes .pair .lane.coach h3 { text-align: right; } .tm-cols .tm-floor .lanes .pair .lane.coach .crow { justify-content: flex-end; }
    .tm-cols .tm-floor .lanes .lane.bench { margin-top: 10px; }
    .tm-cols .tm-courtcard > .tm-hint { margin-top: 6px; font-size: 11px; }
  }
  .tm-left { display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 13px; color: var(--text-secondary); }
  .tm-left select { font: inherit; padding: 4px 8px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary); }
  .tm-kbtns { display: block; }
  #team li[data-cmp] .tm-what { cursor: pointer; }
  .tm-warn { font-size: 12px; font-weight: 600; color: var(--warning, #b45309); margin-top: 4px; }
  .tm-keep { display: inline-block; margin: 6px 14px 0 0; padding: 0; border: 0; background: none; color: var(--series-1); font: inherit; font-size: 13px;
    text-align: left; cursor: pointer; }
  .tm-kept { font-size: 14px; margin: 10px 0 0; }
  .tm-kept .linkbtn { font-size: 13px; }
  .tm-trades { border: 0; background: none; padding: 0; font: inherit; color: inherit; cursor: pointer; }
  /* undo: words on wide screens; on phones ↶ and ▾ with «Undo last» / «Undo all» */
  .tm-undo { display: contents; }
  .tm-ico, .tm-dd { display: none; }
  @media (max-width: 699px) {
    .tm-undo { display: inline-flex; }
    .tm-undo > #mUndoLast { border-radius: 999px 0 0 999px; padding: 6px 12px; font-size: 18px; line-height: 1; }
    .tm-ico { display: inline; }
    .tm-lbl, .tm-undo > #mUsed { display: none; }
    .tm-dd { display: inline-grid; place-items: center; position: relative; border: 1px solid var(--border); background: var(--surface-1);
      color: var(--text-primary); border-radius: 999px; padding: 0 12px; font-size: 14px; }
    .tm-undo > #mUndoLast + .tm-dd { border-radius: 0 999px 999px 0; border-left: 0; }
    .tm-dd select { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; font-size: 16px; cursor: pointer; }
  }
  /* wide screens: the to-do list and the court side by side */
  @media (min-width: 1000px) {
    .tm-cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.85fr); gap: 14px; align-items: start; }
    .tm-cols .tm-floor .chip .cs { font-size: 10px; }   /* the court has sidelines */
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
  .tm-up { color: var(--good, #1e8e3e); font-size: 10px; margin-left: 2px; } .tm-down { color: var(--critical); font-size: 10px; margin-left: 2px; }
  .tm-planned { color: var(--good); }
  .tm-ready .tm-why { display: block; font-weight: normal; }
  /* a long name is cut («Beauch…»), the marks after it (🚑 $ 🆕) always show */
  .chip .cn.cnx { display: flex; justify-content: center; gap: 3px; }
  .chip .cn.cnx > span { flex: none; } .chip .cn.cnx > .nm { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .chip .few { cursor: help; padding: 2px; margin: -2px; }
  .tm-over { color: var(--critical); font-size: 13px; margin: 6px 2px 0; }
  .tm-slot { width: 31%; max-width: 128px; border: 2px dashed var(--court-line); border-radius: 10px; padding: 12px 4px;
    background: color-mix(in srgb, var(--surface-1) 55%, transparent); color: var(--text-secondary); font: inherit; font-size: 12px; cursor: pointer; }
  .lane .tm-slot { width: calc(25% - 5px); }
  @media (max-width: 420px) { .lane .tm-slot { width: calc(33.3% - 4px); } }
  .tm-slot b { display: block; font-size: 18px; color: var(--accent); }
  #team .chip { touch-action: none; user-select: none; -webkit-user-select: none; cursor: grab; transition: transform .15s ease; }
  #team .tm-setchip { touch-action: auto; cursor: pointer; }
  #team .tm-sellchip { touch-action: auto; cursor: pointer; position: relative; }
  .tm-sellchip .tm-x { position: absolute; top: -7px; right: -7px; width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center;
    font-size: 11px; font-weight: 700; background: var(--surface-0); color: var(--text-primary); border: 1px solid var(--border); }
  .tm-sellchip.tm-new { outline: 2px solid var(--good); outline-offset: -2px; }
  .tm-slot small { display: block; font-size: 10px; color: var(--text-muted); font-weight: 400; margin-top: 2px; }
  .tm-lift { opacity: .35; }
  .tm-target { outline: 3px solid var(--series-1) !important; outline-offset: 2px; transform: scale(1.04); }
  .tm-ghost { position: fixed; z-index: 50; pointer-events: none; width: 104px; transform: translate(-50%, -60%) rotate(-3deg);
    box-shadow: 0 10px 24px rgba(0,0,0,.25); }
  .tm-flash { animation: tmflash .6s ease; }
  @keyframes tmflash { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--good) 70%, transparent); } 100% { box-shadow: 0 0 0 12px transparent; } }
  .tm-toast { pointer-events: none; position: fixed; left: 50%; bottom: calc(18px + var(--bnav, 0px) + env(safe-area-inset-bottom, 0px)); transform: translateX(-50%) translateY(20px);
    opacity: 0; background: var(--text-primary); color: var(--surface-1); border-radius: 12px; padding: 10px 14px; font-size: 14px;
    z-index: 60; transition: opacity .2s, transform .2s; max-width: calc(100% - 32px); text-align: center; pointer-events: none; }
  .tm-toast.on { opacity: 1; transform: translateX(-50%) translateY(0); }
  @media (prefers-reduced-motion: reduce) { #team *, .tm-toast { transition: none !important; animation: none !important; } }`;
  document.head.appendChild(css);

  if (typeof P === "undefined" || !GAME()) importFromHash();
  let justMoved = false;
  try { justMoved = !!sessionStorage.getItem("moved"); sessionStorage.removeItem("moved"); } catch (e) {}
  if (justMoved) toastSoon(L("Η ομάδα και οι επιλογές σου ήρθαν στο coachdime.com", "Your team and settings came over to coachdime.com"));
  if (typeof P === "undefined" || !GAME()) adoptMove(justMoved);
  // the link pasted into a tab that already shows the app: only the #hash changes, no reload
  window.addEventListener("hashchange", () => {
    if (!/[#&]t=/.test(location.hash) || (typeof P !== "undefined" && GAME())) return;
    importFromHash(); setup = null; mode = null;
    if (typeof P !== "undefined" && P) { render(); if (typeof showTab === "function") showTab("team"); }
  });
  // a short status for the «Round» page: null = no team yet (public edition)
  function summary() {
    try {
      const t = GAME() ? gameTeam() : load();
      if (!t) return null;
      if (!t.roles) return { steps: null, bank: t.bank };
      const pl = plan(t);
      const cap = pl.targetCap != null ? (pl.aRows.find((r) => r.id === pl.targetCap) || row(pl.targetCap)) : null;
      const pending = pl.items.length + (t.confirmed ? 0 : 1);
      return { steps: pending, trades: pl.tradesNow ? pl.trs.pairs.length : 0, captain: cap ? sur(cap.name) : null,
        bank: t.bank, name: t.game ? t.name : null, inRound: pl.inRound };
    } catch (e) { return null; }
  }
  window.TEAM = { render, summary, encode, decode, KEY, sizeFloors, backup };
})();
