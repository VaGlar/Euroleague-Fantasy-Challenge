# 004 — Do we choose the model with the right metric?

**Date:** 28/9/2026 · **Status:** ❌ no change needed (the current metric doesn't mislead us)

## Question
The backtest chooses the form weights by the lowest mean absolute error over all players. But fantasy decisions are about whom you pick with 100 credits: stars, and also cheap substitutes who must play. Would a metric closer to the decisions choose different weights?

## Method
- **Pool:** shared code `research/_lib.py`. Each round, everyone who had appeared in a box score before it, about 280–320 players. A player who didn't play brings 0.
- **Prices:** estimated. This season's starting prices as a function of last season's output (correlation 0.92) applied one season back. For players without history, the price comes from their first 5 games.
- **Choosing the weights:** the 105 combinations of form weights were scored on the first half of the season with four metrics:
  - mean absolute error (today's),
  - RMSE,
  - the right order within price bands (4–6, 6–8, 8–10.5, 10.5+ credits),
  - decision points: each round, the best squad within budget according to the predictions, and how many *real* fantasy points it would have brought (five and 6th 100%, bench 50%, captain ×2).
- **Judged** on the second half of the season with the decision points, against today's weights. Two seasons: 2025–26 and 2024–25.

## Results: squad points per round, second half

| Weights chosen by | 2025–26 | 2024–25 |
|---|---|---|
| **Today's** (0.10 / 0.35 / 0.50) | **149.9** | **161.1** |
| Mean absolute error | 147.9 (−2.0 ± 2.7) | 163.9 (+2.8 ± 1.8) |
| RMSE | 146.9 (−3.0 ± 2.5) | 161.9 (+0.8 ± 1.2) |
| Order within price bands | 147.4 (−2.4 ± 3.1) | 151.0 (−10.1 ± 6.7) |
| Decision points | 143.5 (**−6.4 ± 2.1**) | 159.2 (−1.9 ± 3.6) |
| Plain season average (no model) | 145.4 | 157.1 |
| Knowing the outcome (the maximum) | 281.9 | 276.9 |

(± = standard error of the difference per round.)

## Conclusions
- **No metric steadily beats today's weights.** All the differences are at noise level, except one, which is negative.
- **Optimizing directly on decision points overfits.** The metric that looks «more right» gave the worst results in 2025–26 (−6.4 ± 2.1). A squad's points are so noisy per round that choosing by them chooses luck. Error metrics over ~5,000 predictions are more stable.
- **The model beats the plain average** by ~4–4.5 points per round (~3%) in both seasons. Over 34 rounds that is about 140–150 points.
- **The gap to the best possible is huge** (~150 vs ~280). That's basketball's noise, which no model catches.

## Limits
- A new squad every round, without the 4-trade limit, without turns and without a coach. It tests the quality of the picks, not a season simulation.
- The prices are estimates and stay fixed all season.
- The backtest knows no injuries or news. Live operation does, so the absolute numbers are conservative.
- Today's weights were chosen on the whole 2025–26 season, so they have a small edge in 2025–26. In 2024–25 they are cleanly out of sample.

## Decision
We keep today's metric and today's weights. The decision-points test (`_lib.squad_points`) stays as an evaluation tool for future experiments, **not for choosing parameters**.
