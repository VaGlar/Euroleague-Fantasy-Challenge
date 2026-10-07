# 012(c) — Return from absence: he plays, but how much?

**Why:** 015 showed, as a side finding, that players with a previous season but few games this season mid-season
are overestimated. The form counts only the games he **played**, so after weeks out the player
is predicted at his «healthy» level, while he usually returns with fewer minutes.

## Method
- **A feature known before the round:** `miss3` = in how many of his team's last 3 games
  the player didn't set foot on court (no row in the box score or 0 minutes).
- **A fair test:** the app knows who is still out (the game's availability sets him to 0), while
  the historical data don't. So both the current model and the correction get the same «knowledge»: a player who didn't
  play is predicted 0. Only «he plays, but how much» is judged.
- **Correction:** `base × c[miss3]`. `c` is computed on one season (ratio of means) and judged on the other
  (2024 ↔ 2025, walk-forward from round 3).

## Results
**Diagnostic** (players who played; «good» = prediction ≥ 10):

| Missed of the last 3 | 2024: predicted → actual | 2025: predicted → actual |
|---|---|---|
| 0 (all) | 8.8 → 9.7 | 9.1 → 9.7 |
| 1 (good) | 13.5 → 13.4 | 13.9 → 12.9 |
| 2 (good) | 14.1 → 12.5 | 14.3 → 15.0 |
| **3 (good)** | **13.5 → 9.5** (n=34) | **13.4 → 10.1** (n=37) |

- Players returning after **3/3 absences** score **25–30% below** the prediction, in both seasons
  (≈3 standard errors each). Players who missed 1–2 games are predicted correctly.
- Coefficient from one season: 0.72 (from 2024), 0.82 (from 2025).

**Out of sample** (`result.json`, `result_only3.json`):

| Correction | Judged on 2025: error / squad points | Judged on 2024: error / squad points |
|---|---|---|
| none (today) | 5.609 / 5896 | 5.459 / 4967 |
| c for miss3 = 1, 2, 3 | 5.600 / 5904 | 5.446 / **4894** |
| **miss3 = 3 only** | **5.594 / 5899** | **5.448 / 4979** |
| miss3 = 3 only, fixed 0.8 | 5.597 / 5897 | 5.447 / 4979 |

- Correcting 1–2 missed games too: mixed (−73 points in 2024). There's no problem there.
- Correcting **only** the return after 3/3: wins in both seasons, but **a little**: −0.01 in error
  (below the noise floor of 0.03) and +3 / +13 squad points over a season. The group is small (~1 player
  per round), so the overall gain is small, even though the error for that player is large.

## Decision
✅ **Shipped (the owner's choice, 29/09/2026)**, reasoning: the bias is stable and large for that
player (−3.5 to −4 points) and concerns an expensive decision (buying a star who just came back). The overall gain
looks small because the case is rare, not because the error is small.
- **Model:** `base × 0.8` when the player played none of his team's last 3 games
  (`model.absent_last3`, `return_factor` in `config.py`). A fixed value between the two estimates, not
  fitted to either season. Players who missed 1–2 games don't change.
- **App:** a «↩ επιστρέφει» (returning) flag with ⓘ (players list, card, court, trades).
- ⏳ **Recheck** with this season's data mid-season (together with 005).
- 1/10: together with participation (020) the two corrections stacked; see 022.
