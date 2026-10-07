# 016 — Shooting luck: does an unusually hot shooter inflate his form?

**Question:** PIR rewards every made shot (a two +3 vs a miss, a three +4, a free throw +2). Shooting
percentages regress to the mean. So a player who shoots unusually well for a few games is probably overestimated by
the form, and one who shoots badly is underestimated.

## Method (`run.py`)
- **«Corrected» PIR per game:** made shots are replaced with the expected ones, at a percentage «pulled» towards
  a prior: `p = (made + k·p0) / (attempts + k)`, separately for twos, threes and free throws.
  `p0` is the player's last-season percentage, shrunk towards the league's (100 attempts), otherwise the league's.
- The season mean and the last-3 mean are computed with the corrected PIR. The rest of the model stays the same.
- Walk-forward (only what was known before each round), seasons 2024 and 2025. `k` is chosen on one
  season (squad points) and judged on the other.
- `k = 0` isn't exactly today's model: the season mean stays the same, but the last 3 are
  «smoothed» with the player's percentage this season.

## Results (`result.json`)

| k | 2024: error / squad points | 2025: error / squad points |
|---|---|---|
| today | 5.249 / 4652 | 5.165 / 5387 |
| 0 | 5.258 / 4734 | 5.160 / 5418 |
| 25 | 5.265 / 4790 | 5.182 / 5290 |
| 50 | 5.271 / 4800 | 5.189 / 5148 |
| 100 | 5.277 / 4765 | 5.195 / 5167 |
| full (∞) | 5.294 / 4623 | 5.211 / 5133 |

- **The error gets worse for every k > 0 in both seasons.**
- **Out of sample:** the `k` of 2024 (50) judged on 2025 gives **−238** squad points. The `k` of 2025
  (25) judged on 2024 gives **+138**. Opposite signs, so noise.
- For the «good» ones (prediction ≥ 12) the error improves a little in 2025 and gets worse in 2024.

**Why it doesn't work:** shooting in PIR is largely **skill** (who shoots, from where, in what
role), not luck. Also the form already pulls towards the mean: the season mean and last season carry
weight. Shrinking the percentages further removes real signal.

## Decision
❌ **No model change.** A worse error in both seasons, opposite results in squad points.

Shot location data (the EuroLeague API's shot data) would give a cleaner «shot quality», but since the
simpler version shows no signal, it isn't worth the effort now.
