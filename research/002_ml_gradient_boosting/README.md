# 002 — Machine learning (gradient boosting) and minutes played

**Date:** 27/9/2026 · **Status:** ❌ rejected

## Question
Does a more flexible ML model predict better? If so, is the gain down to the algorithm or to new features, such as minutes played?

## Method
- **Test:** rounds 20–38 of 2025–26. **Training:** only on what was known before them (all of 2024–25 and rounds 1–19 of 2025–26), 11,569 rows. **Test set:** 4,477 rows.
- **Models:**
  - the current one,
  - gradient boosting (`HistGradientBoostingRegressor`) with the same features,
  - gradient boosting with minutes played (season mean, last 3, last game, last season),
  - a linear model with the same minutes.
- **Loss function:** two were tried, absolute and squared error (see below).

## Results

| Model | Mean error | RMSE | Spearman | Top-20 hit | Mean prediction (actual 7.92) |
|---|---|---|---|---|---|
| **Current** | 5.295 | 6.965 | 0.541 | 0.300 | 7.70 |
| GBM, same features | 5.294 | – | 0.536 | 0.305 | – |
| GBM + minutes (squared loss) | 5.342 | 6.976 | 0.541 | 0.297 | 8.03 |
| GBM + minutes (absolute loss) | 5.214 | 6.993 | 0.544 | 0.313 | **7.33** |
| Linear + minutes | 5.316 | 6.931 | 0.548 | 0.292 | 8.17 |

## Conclusions
- **The algorithm alone offers nothing.** With the same features, the GBM ties the current model.
- **Minutes played don't help either.** PIR already contains their effect. Only predicting a *change* of role would help, and that doesn't show in the stats before it happens.
- **Trap:** the GBM with absolute loss seems to win 1.5% in mean error, but only because it predicts the **median** (7.33 vs an actual mean of 7.92). Fantasy needs the expected (mean) number of points. With squared loss the gain disappears.
- **Finding for the current model:** for each round's top 20 it predicted 17.23 PIR and they brought 16.04, about 7% less («winner's curse»). It doesn't change the picks, but it inflates the xPTS the user sees.

## Decision
No ML. New experiments: 003 (calibrating the high predictions) and 004 (the evaluation metric). Again at the end of the season with 3 seasons of data (007).
