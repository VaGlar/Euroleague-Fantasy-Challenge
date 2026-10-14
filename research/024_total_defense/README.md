# 024 — The total PIR a defence allows: does it add to the model?

**Date:** 14/10/2026 · **Status:** ❌ not in the model · ✅ shown in «Άμυνες»

## Question
The defences' table shows the PIR each team allows per position. Should it also show the total, and should the total
count (a little) in the model?

## Method (`run.py` → `result.json`)
- **The term:** the total PIR a team's opponents score against it, relative to the league. It is shrunk to half of last
  season's with k = 10 games, as the position term (`pos_dev`) is.
- **Test:** added as a 7th context term (× base, like the others). Walk-forward, dressed players; fitted on the first
  half of a season, judged on the second; two seasons.

## Results

| | 2024–25 | 2025–26 |
|---|---|---|
| Correlation with the mean of the position terms | 0.958 | 0.972 |
| Correlation with the game's pace | 0.38 | 0.27 |
| MAE: current model → with the total | 5.159 → 5.162 | 5.262 → 5.256 |
| Spearman | 0.563 → 0.563 | 0.543 → 0.544 |
| Coefficients (total / position) | 1.33 / **−0.51** | 0.70 / 0.19 |

## Conclusions
- The total is almost the same information as the positions (r ≈ 0.96–0.97): a defence that allows a lot allows a lot
  at every position.
- With both terms in, the fit shares the weight between them unsteadily (in 2024–25 the position term turns negative).
- The error moves ±0.005, which is noise.

## Decision
Not in the model: the position term is the more specific one and already carries this. Shown as a «Σύνολο» column in
«Άμυνες» (`model.total_allowed`), with an ⓘ that says it doesn't enter the model.
