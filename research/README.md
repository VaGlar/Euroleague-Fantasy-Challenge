# R&D — experiments and ideas

Every idea to improve the model or the product is recorded here: what was tried, how, what came out and what was decided. We keep **the failures too**, so they aren't retried without a reason and so that every choice visibly rests on evidence.

## Rules

1. **Each experiment has its own folder** `NNN_name/` with:
   - `README.md`: question, method, results, decision,
   - `run.py`: the code, so it can be run again,
   - `result.json`: the numbers as they came out.
2. **Out-of-sample test:** the model is judged only on rounds it didn't see in training (walk-forward).
3. **Always compared with the current model** on the same test. A change ships only if it wins clearly, not within the noise.
4. **The code here doesn't run in the update** and isn't needed for operation. Extra libraries: `research/requirements.txt`.

## Index

| # | Question | Status | Decision |
|---|---|---|---|
| [001](001_coefficient_stability/) | Are the model's parameters stable? Does a second season help? | ❌ not shipped | The form weights are stable, the context coefficients aren't. The 2024–25 season doesn't improve things. The parameters stay. |
| [002](002_ml_gradient_boosting/) | Does machine learning (gradient boosting) and minutes played win? | ❌ rejected | No gain. The hint that the top players are overestimated (~7%) wasn't confirmed in 003. |
| [003](003_calibration/) | Calibrating the high predictions (winner's curse) | ❌ rejected | The overestimation of the top players isn't stable (+4% / −2% over two seasons). An isotonic correction makes the picks worse. |
| [004](004_metric_choice/) | Do we measure with the right yardstick? (mean error vs picking the right players, with a budget) | ❌ no change needed | No metric beats the current weights. Selecting directly on squad points overfits. The model beats the plain average by ~4 points/round. |
| 005 | Refit mid-season (~round 17) with this season's data | ⏳ waiting for data | Ship only if it wins out of sample. |
| 006 | `/ρωτα` (ask) over the article archive (RAG) | ⏳ on hold | The article archive is already collected (private data repo). The daily summary stays as it is. See `docs/PRODUCT.md`. |
| 007 | ML again, with 3 seasons of data and new features (e.g. injured teammates) | ⏳ end of season | — |
| [008](008_transfer_policy/) | The trade optimizer in a season simulation (horizon, weights, minimum gain) | ❌ no change needed | Trades are worth ~500 points/season. Use all 4. A minimum gain of 0–4 is equivalent, 6 costs. A long horizon hurts. The current settings are among the best. |
| [009](009_bias_or_noise/) | The error that remains: noise or a missing signal? | ✅ diagnostic | Not overfitting, not a lack of data. Perfect knowledge of the level would give ~5%, knowing the game's minutes ~22%. The missing signal is in the game's features → 010. |
| [010](010_minutes_signals/) | Where do the minutes go? (a) teammates' absences, (b) role change, (e) rotation depth | ❌ rejected | Position matters in how minutes are shared, but the gain is below the noise. **Side finding: knowing the absences is worth +10 to +19 points/round** → 011. |
| 011 | Fresh availability data: an update shortly before the deadline on game days | ✅ shipped | An update 3 hours before the first game of each game day (Worker). Next: measure the accuracy of the availability data in tracking. |
| [012(c)](012_injury_return/) | Returning after an absence: he plays, but how much? | ✅ shipped | Players returning after 3/3 absences score 25–30% below the prediction in both seasons. A ×0.8 correction for them only (wins in both, a little overall: ~1 player/round) and the «↩ returning» flag. Recheck mid-season. |
| 012 (d, f, g) | The other minutes hypotheses from 010: double round (d), pace × position (f), end of season (g) | ⏳ on hold | — |
| 013 | Value of price changes in trades: should the optimizer prefer players with a predicted rise («$»)? Two steps: (1) how well we predict «$» (predicted vs real change in `prices.csv`), (2) the 008 season simulation with moving prices, with/without a weight on the credits gain. | ⏳ waiting for 4–5 rounds of prices | — |
| 014 | POP (% of managers who own the player): (1) does the crowd know something the model doesn't — do high-POP players beat their xFPT? (2) does the change in POP predict the price change (helps 013)? (3) differentials: when is a high-xFPT, low-POP player worth it for the ranking (not for points), with a ranking simulation. | ⏳ POP logged per round in `prices.csv` since Round 2; needs 5–6 rounds | — |
| [015](015_newcomer_prior/) | Newcomers to the EuroLeague with 1–3 games: does the model trust one game too much? | ❌ no model change · ⏳ again with real prices | The «good» newcomers were overestimated in 2025 (17.8 → 12.0 after 1 game), not in 2024. Neither shrinkage nor a correction wins in both seasons. The app gets a «νέος · N ματς» (new · N games) flag. Side finding for 012(c): players with few games mid-season (back from injury) are overestimated too. **30/9: shipped without a backtest** (no old prices exist): the price-based estimate counts as 2 games and fades as he plays (Wallace 0 → 6.5, Crowder 20.9 → 13.2; again after Round 3). Since 30/9 it applies to everyone with 1–10 games this season, not only newcomers (Motley: −13 and 1 in 2 games, 10cr → 0 xFPT). Recheck with this season's prices at Round 6–8. |
| [016](016_shooting_luck/) | Shooting luck: does an unusually hot shooter inflate his form? | ❌ rejected | Shrinking the shooting percentages makes the error worse in both seasons; squad points move the opposite way (+138 / −238). Shooting in PIR is mostly skill and the form already pulls towards the average. |
| [017](017_fouls_and_coaches/) | Minutes: (A) fouls × an opponent that draws fouls, (C) a coaching change mid-season | ❌ rejected | Fouls are already in the history; the matchup adds nothing. A coaching change doesn't beat a placebo (the same recipe on teams without a change) and loses squad points. **Side finding:** the mean of the recent ≤ 10 games cuts the error by ~0.15–0.19 for everyone → 018. |
| [018](018_form_window/) | Form window: the mean of recent games (8–10) in the blend, tested on error and on squad points | ❌ rejected | With known absences (as in live operation) the gain is ~0.01 (noise) and squad points drop in 2025–26 in every variant. The gain in 017 was the absences counted as 0, not the form. |
| [019](019_availability/) | How accurate is availability (game + news)? | ✅ bug fixed · ⏳ again in 4–5 rounds | The game's «0» and «0.5» are right (0% / 50% played); 4/105 surprises at «1». **Bug:** the news' «out» written as «Josh Nebo» (instead of «NEBO, JOSH») were silently ignored — 33 of 67. Fixed. (1/10: the same bug in another form — names in Greek — fixed with `news.resolve_names`.) |
| [020](020_participation/) | Participation: xFPT × the probability of being in the 12 (players like Dessert, few minutes) | ✅ shipped | Final form (this season's, k=6, p0=0.95): MAE −0.023 / −0.037 in both seasons; squad points +26 / −58 (noise). Owner's decision: honest numbers. Limit: it can't tell a long injury from a long spell out of the rotation; «not on the EuroLeague roster» is pending. |
| [021](021_price_prior/) | The price as «memory» for players with few games: weight K0 after the 1st game, ×decay per game (`grid.py`: R2+R3) | ✅ K0=2, decay 0.5 for everyone (30/9) · ⏳ proposal: newcomers K0≈6, returning players 2 | The rule in force is taken out of the logs and each (K0, decay) is applied again to the «raw» prediction. 455 appearances (R2 224, R3 231). No price: MAE 6.35; current (2, 0.5): 5.67; newcomers 6 / returning 2: 5.56 (newcomers 6.08→5.68, returning the same 5.52). The decay can't be told apart yet (0.25–1 within 0.03). Bias −0.4 everywhere. 2 Rounds: too few. |
| [022](022_return_x_participation/) | Return from absence: the ×0.8 return factor (012c) together with participation (020) | ✅ shipped (1/10) | Together they give ×0.53–0.54 to a player back after 3 absences, while he brings ×0.74–0.82 of his base: an underestimate of −0.9/−1.2 FPT (−1.7/−2.4 for players with a base ≥10). If an absence still running (≥3 games) is left out of participation, the gap almost vanishes (+0.1/−0.2), squad points +10 in both seasons, MAE the same (within the noise). |

**Status:** ✅ shipped · ❌ tried and rejected · 🔬 planned · ⏳ on hold

## How we measure out of sample

- **Walk-forward:** each round is predicted only with what was known before it.
- **Training and testing on different parts:** e.g. the first half vs the second half of the season, and a second season (2024–25) for confirmation.
- **Metrics:**
  - mean absolute error (MAE) and RMSE in PIR,
  - Spearman: the right order per round,
  - top-20 hit,
  - squad points with a budget (004).
- **Bounds with knowledge of the outcome (009):** show how much improvement is possible.

## Reference point

The current model (form × context, coefficients by ridge regression on the 2025–26 season) on the test of experiments 001/002 has:
- a mean error of **5.26–5.30 PIR** per player and game,
- Spearman **0.54**,
- top-20 hit **~30%**.

Experiments 003 and 004 use the shared code in `_lib.py`. Each round a squad is built with a budget of 100 credits, with estimated prices, from everyone who appeared in a box score. A player who didn't play brings 0, so the cheap substitutes who don't play count too.

In the budget squad test (004), the current model brings **~150–161 points per round**, vs ~145–157 for the plain season average and ~280 for the best possible.

The noise of PIR (standard deviation ~7 per game) sets a natural limit: improvements below ~0.03 PIR in the mean error count as noise.
