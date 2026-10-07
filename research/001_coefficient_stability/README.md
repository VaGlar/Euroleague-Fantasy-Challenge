# 001 — Parameter stability and a second season

**Date:** 27/9/2026 · **Status:** ❌ not shipped (nothing beat the current model)

## Questions
1. If we run the backtest on the 2024–25 season, do we get the same parameters as for 2025–26?
2. Do the parameters change within a season (start / middle / end)?
3. Does training on 2024–25 as well improve the prediction?

## Method
- Walk-forward backtest (`elf/backtest.py`) on the 2024–25 and 2025–26 seasons. For 2024–25 the 2023–24 data were downloaded too, used as «previous season».
- The form weights come from a grid search. The context coefficients come from ridge regression.
- Out-of-sample test: the second half of 2025–26, with coefficients from different sources.

## Results

Parameters per season:

| | 2024–25 | 2025–26 |
|---|---|---|
| Form weights (last 3 / season / last season) | 0.09 / 0.45 / 0.45 | 0.11 / 0.37 / 0.53 |
| Defence by position | 0.11 | 0.49 |
| Pace | 0.90 | 0.50 |
| Home | +0.03 | +0.045 |

Parameters per third of 2025–26:

| Rounds | Defence | Pace | Home | Season / last season |
|---|---|---|---|---|
| 1–13 | 0.28 | −0.20 | 0.07 | 0.37 / 0.56 |
| 14–26 | 0.60 | 0.10 | 0.02 | 0.37 / 0.56 |
| 27–38 | 0.60 | 0.64 | 0.05 | 0.64 / 0.18 |

Second half of 2025–26, out of sample (mean PIR error):

| Coefficients from | Error |
|---|---|
| First half of 2025–26 (as today) | **5.262** |
| 2024–25 + first half of 2025–26 | 5.274 |
| 2024–25 only | 5.286 |
| No context (form only) | 5.295 |

## Conclusions
- **The form weights are stable** across two seasons: the form of the last 3 games predicts very little. A reliable finding.
- **The context coefficients are not stable.** Pace even changes sign between thirds. It's noise: effects of the order of 5% can't be measured steadily with ~3,000 observations and noise of ~5 PIR. We don't interpret the coefficients one by one.
- **Late in the season this season counts more.** The model already covers that, as the weight of last season fades with every game.
- **2024–25 doesn't improve training.** The differences are within the noise.

## Decision
The parameters stay locked. A mid-season refit of this season is planned (experiment 005), to ship only if it wins out of sample. The 2023–24 data stay in the repo for future checks.
