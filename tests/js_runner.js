// Runs web/opt.js on JSON cases from stdin (used by tests/test_js_optimizer.py).
const opt = require("../web/opt.js");
let buf = "";
process.stdin.on("data", (d) => (buf += d)).on("end", () => {
  const cases = JSON.parse(buf);
  const out = cases.map((c) => {
    if (c.kind === "lineup") {
      const r = opt.lineup(c.squad, { inRound: c.inRound });
      return r && { objective: r.objective, team: r.team.map((p) => ({ id: p.id, role: p.role, captain: p.captain })) };
    }
    if (c.kind === "plan") {
      const r = opt.deferLaterTurns(c.team);
      return r.plan.map((x) => [x.bench.id, x.start.id]);
    }
    if (c.kind === "transfers") {
      const r = opt.transfers(c.squad, c.pool, c.bank, { maxTrades: c.maxTrades, minGain: c.minGain, keep: c.keep || [] });
      return { gain: r.gain, bankAfter: r.bankAfter, n: r.pairs.length,
        squad: r.squad.map((p) => ({ id: p.id, position: p.position, price: p.price, team: p.team })) };
    }
    return null;
  });
  process.stdout.write(JSON.stringify(out));
});
