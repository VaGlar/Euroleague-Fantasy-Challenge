# 015 — Newcomers to the EuroLeague: one game is not a level

**Why:** in round 2 of 2026 the model suggested Crowder (25 PIR in his 1st game, no previous EuroLeague season)
and Fodzo Dada. When the previous season is missing, the player's «base» is only this season's games, i.e.
one.

## Method
Rounds 2–8 of the 2024 and 2025 seasons (walk-forward, as in `_lib`). The settings are chosen on one season
and judged on the other.

1. **Shrinkage towards a starting estimate** (`run.py`): `base = (g·form + k·prior)/(g + k)`. As the prior, the mean
   of the other season's newcomers per position. The price wasn't used, because for old seasons we don't have it
   without «peeking» at the first games.
2. **Calibration and correction** (`calib.py`): prediction vs actual by number of games. Then a linear correction
   `a + b·prediction` for newcomers with ≤5 games.

## Results
- **The «good» newcomers with few games are overestimated** (prediction ≥12): strongly in 2025 (1 game: 17.8 → 11.96,
  2: 16.7 → 10.3, 3: 16.3 → 9.7), while in 2024 it doesn't show (16.6 → 15.3, 18.2 → 19.6). The samples are small
  (10–23 per group).
- **Shrinkage towards the position mean:** a worse error for every value of k. The mean (3–5 PIR)
  includes the substitutes and drags the good ones down too. In squad points: +65 in 2024,
  −16 in 2025.
- **Linear correction:** +34 squad points and a smaller error when judged on 2025. −9 points and a larger
  error when judged on 2024.
- **Side finding:** players with a previous season but only 4–5 games **mid-season** are overestimated too
  (14.8 → 7.4 in 2024, 15.5 → 9.8 in 2025). They are almost certainly players back from injury or out of
  the rotation, i.e. 012(c).

## Decision
❌ **No model change.** No correction wins clearly in both seasons.

✅ **In the app:** a «νέος · N ματς» (new · N games) flag with ⓘ on players without a previous EuroLeague season and with ≤4 games.
Their prediction is uncertain and the user should know it.

⏳ **Next:** the same test with the **real price** as the prior, on the 2026 data (`prices.csv` collects
prices since round 1). After ~6 rounds, together with 013/014.

**30/9 (see 021):** shipped without a backtest — no old prices exist — as a price-based estimate that counts as
extra games and fades game by game, first for newcomers, then for everyone with few games this season.
