# 023 — The live predictions run high at the top: why, and should we correct?

**Date:** 14/10/2026 (R1–R4, R5 partly played) · **Status:** ❌ no model change · ⏳ again after R10–R12

## Question
The autopilot scores ~20 points/round under its own xFPT (R1 −20.5, R2 −23.8, R3 −20.9, R4 −8.4). The live log shows
why: overall the predictions are unbiased (−0.26), but the players predicted high bring less. 003 found no stable
overestimation of the top (+4% / −2%), but it measured the **second half** of past seasons. Also asked: with five rounds
played, is a light refit of the coefficients with this season worth it?

## Method (`run.py` → `result.json`)
- **A, the live log:** x_pred at tip-off vs real points, by level, and the plain average (naive) on the same rows.
- **B, the backtest model** (form × context, without the live extras: participation, price memory, return factor) on this
  season's rounds 3–5.
- **C, a correction:** linear, and «shrink the top» (above k only a share s counts), fitted on R1–R3, judged on R4–R5.
  Error, bias of the top 20, and squad points with the real prices of that round.
- **D, refit:** last season's coefficients, vs last season + this season's R≤3 (×1, ×3, ×5), judged on R4–R5.
- **E, how fast last season fades** (`prev_decay_k` 2–25), rounds ≤ 8 of three seasons.
- **F, an early-season shrink** (rounds ≤ 8 only), fitted on one past season and judged on the other with squad points.

## Results

**A: live, by predicted level (1,300 predictions, R1–R5)**

| xFPT | n | real − model | real − plain average (same players) |
|---|---|---|---|
| 0–5 | 357 | +0.6 | +0.9 |
| 5–10 | 369 | −0.3 | −0.4 |
| 10–15 | 193 | −2.3 | −3.2 |
| 15–20 | 85 | −2.0 | −3.8 |
| 20+ | 24 | −6.1 | −10.2 |

Each round's top 20 by the model: predicted 17.6, actual 15.0 (−15%); the plain average said 19.8 for them.

- **B:** the backtest model shows the same pattern on this season (15–20: −2.6, 20+: −4.5), so the live extras are not
  the cause.
- **E: the top 20 per round, rounds ≤ 8, three seasons:** −2.5 to −3.2 (2024), −2.6 to −3.2 (2025), −3.2 to −4.0
  (2026), with any `prev_decay_k`. The MAE barely moves (best k 4–10, as now: 5).
- **C (R4–R5 only):**
  - linear: MAE 4.52 → 4.75, worse;
  - shrink-top: MAE 4.46, but it overcorrects the top (+2.6);
  - squad points: equal in R4, +18 in R5 (only turn 1 played: noise).
- **F (squad points per round, rounds 3–8):**
  - fitted on 2024, judged on 2025: **−6.3** (k=15, s=0.6);
  - fitted on 2025, judged on 2024: **+11.2** (k=8, s=0.7);
  - the error improves by 0.002–0.03.
- **D:**
  - MAE on R4–R5: 5.355 (now) → 5.339 / 5.317 / 5.303 with this season ×1 / ×3 / ×5;
  - Spearman and top-20 the same;
  - the pace coefficient jumps 0.50 → 0.81 / 1.31 / 1.69.

## Conclusions
- **The top is overestimated early in every season (~15% in rounds ≤ 8), not only this one.** It is regression to the
  mean: a player who started hot is predicted high, and the plain average overestimates him even more (the model
  already pulls half the way back, through last season). 003 missed it because it looked at the second half.
- **The autopilot's −20/round is this effect:** the optimizer picks exactly the highest predictions, 11 players and a
  captain ×2.
- **A correction doesn't help the picks:** the two past seasons disagree (−6 / +11) and on k, s. It would change the
  numbers shown more than the choices.
- **The refit is within the noise** (−0.05 MAE) and its coefficients aren't stable (pace ×3.4). This agrees with 001
  (the context coefficients aren't stable) and 005 (refit around round 17).

## Decision
- **No model change.** The predictions stay as they are; their order (Spearman, top-20) is what the picks use.
- **Shown in the app:** the team's xFPT early in a season is ~15% optimistic at the top. Optional: an ⓘ note on the
  autopilot's xFPT.
- **Again after R10–R12:** does the top's overestimation fade as the season's games add up (as the second half of 003
  says)? If not, a correction fitted on two seasons' early rounds together. The refit waits for 005.
