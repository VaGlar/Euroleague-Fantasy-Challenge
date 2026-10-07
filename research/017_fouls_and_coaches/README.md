# 017 — Minutes: fouls and a coaching change

**Date:** 29/9/2026 · **Status:** ❌ both rejected · 🔬 side finding about the form → 018

## Question
- **(A) Fouls.** A player who fouls a lot plays less. But that is already in his history (minutes, and PIR subtracts the fouls). The history doesn't know **the night's opponent**: a team that draws many fouls (high `pfd`) gets a player who is whistled easily into trouble.
- **(C) A coaching change.** After a new (or interim) coach, the old history describes another rotation. The coach's style in general (tight/loose rotation) was already checked by 010(e): it's in each player's history.

## Method
- **A:** three signals, known before the game:
  - `opp_pfd`: fouls the opponent draws per game vs the average,
  - `foul_x_opp`: (the player's fouls per minute / average − 1) × `opp_pfd` × minutes × PIR per minute,
  - `fouled_out`: fouled out with 5 fouls in the previous game.

  Trained on the first half of 2025–26, tested on the second half and the whole of 2024–25, as in 010. The hypothesis was also checked directly on the game's minutes. A budget squad test followed.
- **C:** the coaching changes come from the data: a coach with a start date after the start of the season. There were 5 changes in 2024–25 and 14 in 2025–26, interims included.
  - For the team's next 10 games, the season mean becomes a mix: w · (mean after the change) + (1 − w) · (old), with w = n / (n + k).
  - k was chosen on one season and judged on the other.
  - **Placebo test:** the same recipe, on the same dates, on the teams that did **not** change coach.

## Results

**A — fouls:** no signal.

| | Coefficient (± s.e.) | ΔMAE 2025 2nd half | ΔMAE 2024 |
|---|---|---|---|
| Minutes: fouls × opponent | −0.6 ± 0.5 minutes | — | — |
| `opp_pfd` | −2.2 ± 1.7 PIR | +0.002 | −0.002 |
| `foul_x_opp` | −0.4 ± 1.0 | −0.001 | +0.001 |
| `fouled_out` | +1.4 ± 0.6 (!) | −0.002 | −0.001 |
| Squad points/round | | −0.5 ± 2.0 | +0.9 ± 1.4 |

- The sign on the minutes is as expected, but within the noise.
- A player who fouled out plays **better** in the next game: regression to the mean, not a «foul problem» that continues.

**C — coaching change:**

| | 2025–26 | 2024–25 |
|---|---|---|
| Rows after a change | 1,342 | 624 |
| Starters' minutes shift (5 before / 5 after): at the change · elsewhere | 5.9 · 4.6 | 3.1 · 4.8 |
| ΔMAE, out of sample | −0.31 (k=2) | −0.15 (k=0) |
| **ΔMAE of the placebo** (teams without a change) | **−0.16** | **−0.19** |
| ΔMAE of those who matter (prediction ≥ 12) | −0.68 | +0.11 |
| Squad points in the rounds after a change | **−155** | +15 |

## Conclusions
- **(A) Rejected.** The physical explanation holds within a game, but it isn't predictable before it. A player's fouls are already in his history, and the matchup adds nothing measurable.
- **(C) Rejected.**
  - In 2024–25 a coaching change does nothing more than the placebo. The minutes even moved less than at random points.
  - In 2025–26 there's a small extra gain in error, but squad points fall.
  - With 5–14 changes a year, the sample is far too small to support a rule.
- **Side finding, and more interesting:** the placebo shows that the mean of the last ≤ 10 games, in place of the season mean, cuts the error by ~0.15–0.19 **for all teams**. That's above the noise floor (0.03). Maybe the form weighs the season too much mid-year.
  - Caution: 004 showed that weights that win on error can lose on squad points.
  - So it needs its own test, with squad points in both seasons → **018**.

## Decision
- No model change.
- New experiment **018: form window.** A mean of recent games (e.g. the last 8–10) as a fourth term of the blend or in place of the season, tested on error **and** on squad points.
