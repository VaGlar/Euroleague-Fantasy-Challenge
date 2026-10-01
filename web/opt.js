// In-browser optimizer for the public edition: same rules and objective as
// elf/optimize.py (checked against it by tests/test_js_optimizer.py).
//
// Player: {id, position: "Guard"|"Forward"|"Center"|"Head Coach", price, x_now, x_h,
//          turn, played, cur_role, cur_captain}
// Roles: "5άδα" (starting five), "6ος" (sixth man), "πάγκος" (bench, 50%), "coach".
(function (root) {
  const COURT = ["Guard", "Forward", "Center"];
  const SQUAD = { Guard: 4, Forward: 4, Center: 2, "Head Coach": 1 };
  const BENCH = 0.5;
  const LATER_PENALTY = 1000;
  const PLAN_MIN_X = 5;
  const MAX_PER_CLUB = 6;   // the game's rule: up to 6 players from the same EuroLeague club (as optimize.py)
  const num = (v) => (typeof v === "number" && isFinite(v) ? v : 0);

  function combos(n, k) {                 // all k-subsets of 0..n-1 (as index arrays)
    const out = [], cur = [];
    (function rec(start) {
      if (cur.length === k) { out.push(cur.slice()); return; }
      for (let i = start; i <= n - (k - cur.length); i++) { cur.push(i); rec(i + 1); cur.pop(); }
    })(0);
    return out;
  }
  const C10_5 = combos(10, 5);
  const covers = (ps) => COURT.every((pos) => ps.some((p) => p.position === pos));

  // players who play after the current turn (earliest turn among unplayed court players)
  function laterTurnIds(squad) {
    const court = squad.filter((p) => p.position !== "Head Coach" && !p.played);
    const turns = court.map((p) => p.turn).filter(Boolean);
    if (!turns.length) return new Set();
    const first = Math.min(...turns);
    return new Set(court.filter((p) => (p.turn || first) > first).map((p) => p.id));
  }

  // Best five / sixth man / captain for a fixed squad of 10 court players + coach.
  // inRound: the game's rules once the round is under way (a played starter can only
  // go to the bench, a played bench player stays, the armband only to unplayed players).
  function lineup(squad, { inRound = false, value = "x_now", now = "x_now" } = {}) {
    const court = squad.filter((p) => p.position !== "Head Coach");
    const coach = squad.filter((p) => p.position === "Head Coach");
    if (court.length !== 10) return null;
    const later = laterTurnIds(squad);
    const v = court.map((p) => num(p[value])), x = court.map((p) => num(p[now]));
    let best = null;
    for (const five of C10_5) {
      const fp = five.map((i) => court[i]);
      if (!covers(fp)) continue;
      const inFive = new Set(five);
      for (let s = 0; s < 10; s++) {
        if (inFive.has(s)) continue;
        // role constraints for players who already played
        let ok = true;
        for (let i = 0; i < 10 && ok; i++) {
          const p = court[i];
          if (!inRound || !p.played) continue;
          const role = inFive.has(i) ? "5άδα" : i === s ? "6ος" : "πάγκος";
          if (p.cur_role === "πάγκος" && role !== "πάγκος") ok = false;
          if (p.cur_role === "5άδα" && role === "6ος") ok = false;
          if (p.cur_role === "6ος" && role === "5άδα") ok = false;
        }
        if (!ok) continue;
        let base = 0, pen = 0;
        for (let i = 0; i < 10; i++) {
          const full = inFive.has(i) || i === s;
          base += full ? v[i] : BENCH * v[i];
          if (full && later.has(court[i].id)) pen += LATER_PENALTY;
        }
        for (const c of five) {
          const p = court[c];
          if (inRound && p.played && !p.cur_captain) continue;
          const obj = base + x[c] - pen;
          if (!best || obj > best.obj + 1e-9) best = { obj, five, s, c, pen };
        }
      }
    }
    if (!best) return null;
    const inFive = new Set(best.five);
    const team = court.map((p, i) => ({ ...p, role: inFive.has(i) ? "5άδα" : i === best.s ? "6ος" : "πάγκος",
      captain: i === best.c }))
      .concat(coach.map((p) => ({ ...p, role: "coach", captain: false })));
    const coachV = coach.reduce((a, p) => a + num(p[value]), 0);
    return { team, objective: best.obj + best.pen + coachV };
  }

  // Swap plan for later turns (mirror of optimize.defer_later_turns).
  function deferLaterTurns(team0) {
    const team = team0.map((p) => ({ ...p }));
    const court = team.filter((p) => ["5άδα", "6ος", "πάγκος"].includes(p.role));
    const turns = court.filter((p) => p.turn && !p.played).map((p) => p.turn);
    if (!turns.length) return { team, plan: [] };
    const first = Math.min(...turns);
    const turn = (p) => p.turn || first;
    const fits = (out, inn) => out.role !== "5άδα"
      || covers(court.filter((q) => q.role === "5άδα" && q !== out).concat([inn]));
    const byX = (a, b) => num(b.x_now) - num(a.x_now);
    for (const lp of court.filter((p) => ["5άδα", "6ος"].includes(p.role) && !p.played && turn(p) > first).sort(byX)) {
      const cands = court.filter((e) => e.role === "πάγκος" && !e.played && turn(e) < turn(lp) && fits(lp, e));
      if (cands.length) {
        const e = cands.sort(byX)[0];
        [e.role, lp.role] = [lp.role, "πάγκος"];
      }
    }
    const plan = [], used = new Set();
    for (const lp of court.filter((p) => p.role === "πάγκος" && !p.played && turn(p) > first
      && num(p.x_now) >= PLAN_MIN_X).sort(byX)) {
      const cands = court.filter((e) => ["5άδα", "6ος"].includes(e.role) && !used.has(e)
        && turn(e) < turn(lp) && fits(e, lp));
      if (!cands.length) continue;
      const e = cands.sort((a, b) => num(a.x_now) - num(b.x_now))[0];
      used.add(e);
      plan.push({ start: e, bench: lp });
    }
    const cap = team.find((p) => p.captain);
    if (cap && cap.role !== "5άδα") {
      cap.captain = false;
      team.filter((p) => p.role === "5άδα").sort(byX)[0].captain = true;
    }
    return { team, plan };
  }

  // Squad value used for trades (same objective as the ILP in optimize._model):
  // coach full; court: 0.5*v for all + 0.5*v for the six starters + captain's x_now,
  // the five covering G/F/C, captain in the five, sixth man outside it.
  function squadValue(squad, value = "x_h", now = "x_now") {
    const court = squad.filter((p) => p.position !== "Head Coach");
    let tot = squad.filter((p) => p.position === "Head Coach").reduce((a, p) => a + num(p[value]), 0);
    if (court.length !== 10) return -Infinity;
    const v = court.map((p) => num(p[value])), x = court.map((p) => num(p[now]));
    tot += 0.5 * v.reduce((a, b) => a + b, 0);
    let best = -Infinity;
    for (const five of C10_5) {
      let hasG = false, hasF = false, hasC = false, sv = 0, cap = -Infinity;
      const inFive = new Array(10).fill(false);
      for (const i of five) {
        inFive[i] = true; sv += v[i]; if (x[i] > cap) cap = x[i];
        const pos = court[i].position;
        if (pos === "Guard") hasG = true; else if (pos === "Forward") hasF = true; else if (pos === "Center") hasC = true;
      }
      if (!(hasG && hasF && hasC)) continue;
      let six = -Infinity;
      for (let i = 0; i < 10; i++) if (!inFive[i] && v[i] > six) six = v[i];
      const val = 0.5 * (sv + six) + cap;
      if (val > best) best = val;
    }
    return tot + best;
  }

  // Best set of at most maxTrades same-position swaps (beam search).
  // A set of k trades is kept only if it adds >= minGain per trade over the current
  // squad, and each extra trade adds >= minGain (as optimize.transfers).
  // keep: ids never sold; avoid: ids never bought.
  function transfers(squad, pool, bank, { maxTrades = 4, minGain = 2.0, beam = 24, perPos = 16,
    value = "x_h", now = "x_now", keep = [], avoid = [] } = {}) {
    const kept = new Set(keep), avoided = new Set(avoid);
    const budget = squad.reduce((a, p) => a + num(p.price), 0) + bank;
    const owned = new Set(squad.map((p) => p.id));
    // the per-club limit, never below what the squad already has
    const ownedClub = {};
    for (const p of squad) if (p.team) ownedClub[p.team] = (ownedClub[p.team] || 0) + 1;
    const clubOk = (sq, team) => !team || sq.filter((p) => p.team === team).length <= Math.max(MAX_PER_CLUB, ownedClub[team] || 0);
    const cand = {};
    for (const pos of Object.keys(SQUAD)) {
      cand[pos] = pool.filter((p) => p.position === pos && !owned.has(p.id) && !avoided.has(p.id) && p.price != null)
        .sort((a, b) => num(b[value]) - num(a[value])).slice(0, perPos);
    }
    const baseVal = squadValue(squad, value, now);
    let frontier = [{ squad, cost: budget - bank, val: baseVal, key: "" }];
    const bestAt = [{ squad, val: baseVal, cost: budget - bank }];
    for (let k = 1; k <= maxTrades; k++) {
      const next = new Map();
      for (const st of frontier) {
        const ids = new Set(st.squad.map((p) => p.id));
        st.squad.forEach((out, oi) => {
          if (!owned.has(out.id) || kept.has(out.id)) return;   // never swap a player bought in this set, or a kept one
          for (const inn of cand[out.position]) {
            if (ids.has(inn.id)) continue;
            const cost = st.cost - num(out.price) + num(inn.price);
            if (cost > budget + 1e-6) continue;
            const sq = st.squad.slice(); sq[oi] = inn;
            if (!clubOk(sq, inn.team)) continue;
            const key = sq.map((p) => p.id).sort((a, b) => a - b).join(",");
            if (next.has(key)) continue;
            next.set(key, { squad: sq, cost, val: squadValue(sq, value, now), key });
          }
        });
      }
      if (!next.size) break;
      frontier = [...next.values()].sort((a, b) => b.val - a.val).slice(0, beam);
      bestAt.push(frontier[0]);
    }
    let best = bestAt[0], bestK = 0;
    for (let k = 1; k < bestAt.length; k++) {
      const r = bestAt[k];
      if (r.val - baseVal >= minGain * k - 1e-9 && r.val - best.val >= minGain * (k - bestK) - 1e-9) {
        best = r; bestK = k;
      }
    }
    const newIds = new Set(best.squad.map((p) => p.id));
    const out = squad.filter((p) => !newIds.has(p.id));
    const inn = best.squad.filter((p) => !owned.has(p.id));
    // pair by position (as run._pair_trades)
    const order = { Guard: 0, Forward: 1, Center: 2, "Head Coach": 3 };
    const srt = (a, b) => order[a.position] - order[b.position] || num(b.price) - num(a.price);
    out.sort(srt); inn.sort(srt);
    return { pairs: out.map((o, i) => ({ out: o, in: inn[i] })), gain: best.val - baseVal,
      bankAfter: budget - best.cost, squad: best.squad };
  }

  const api = { lineup, deferLaterTurns, transfers, squadValue, laterTurnIds, SQUAD, COURT, MAX_PER_CLUB };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ELFOPT = api;
})(typeof window !== "undefined" ? window : globalThis);
