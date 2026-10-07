# 018 — Form window: does a mean of 8–10 games help?

**Date:** 29/9/2026 · **Status:** ❌ rejected · ✅ explains the side finding of 017

## Question
In 017, the mean «since a date» (≤ 10 team games) cut the error by ~0.15–0.19 for all teams. That mean, however, counted the games the player **missed** as 0, while the model's season mean counts only appearances. The two effects are checked separately:
- **(a) Recent form:** the mean PIR of the last N appearances (N = 8, 10), as a 4th term of the blend.
- **(b) Absences as 0:** the same over his team's last N games, where an absence = 0.

## Method
- **The crux:** in live operation a player who is out is known (injury list, news) and gets 0. So the test runs **with known absences**: a player missing from the box score is predicted 0, and the error is measured on the rest.
- **Weights:** the weight w of the 4th term from the grid 0.1–0.75. Chosen on one season by MAE (004 showed that choosing by squad points overfits) and judged on the other.
- **Metrics:** MAE, MAE of those who matter (prediction ≥ 12), budget squad points.

## Results

Out of sample (weight chosen on the other season):

| | ΔMAE | ΔMAE (≥ 12) | Δ squad points |
|---|---|---|---|
| 2025–26, (a) 10 appearances, w = 0.1 | −0.005 | −0.045 | **−94** |
| 2025–26, (b) 10 team games, w = 0.1 | −0.014 | −0.031 | **−168** |
| 2024–25, (a) 10 appearances, w = 0.1 | −0.002 | −0.034 | +0.2 |
| 2024–25, (b) 10 team games, w = 0.2 | −0.008 | +0.058 | −35 |

- Across the whole grid, in 2025–26 **every** variant loses squad points (−15 to −287). In 2024–25 the results are mixed (−45 to +89).
- No ΔMAE exceeds the noise floor (0.03).

## Conclusions
- **Recent form adds nothing.** The blend (last 3, season, last season) already covers what an 8–10 game window gives.
- **The gain in 017 was the absences, not the form.** With known absences, as in live operation, the ~0.15–0.19 drops to ~0.01. In live operation we already have that signal from the injury list.
- This confirms 010 again: the value lies in the **accuracy and timeliness of availability**, not in the blend.

## Decision
No model change.
