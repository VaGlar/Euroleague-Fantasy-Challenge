# 003 — Calibrating the high predictions

**Date:** 28/9/2026 · **Status:** ❌ rejected (there is no stable overestimation to correct)

## Question
In experiment 002 each round's top 20 seemed to be predicted ~7% above what they brought («winner's curse»). Should we correct (calibrate) the numbers the user sees?

## Method
- **Candidate pool:** each round, everyone who had appeared in a box score before it (shared code `research/_lib.py`).
- **Measured only on players in the 12.** In live operation absences and injuries are covered by the news and the game, while in the backtest they are not. Counting them would «correct» twice.
- **Two corrections**, trained on the first half of the season and tested on the second:
  - linear (`a + b·xPTS`), which changes only the numbers shown, not the picks,
  - isotonic (a monotone curve), which can change the squad picks too.
- **Two seasons:** 2025–26 and 2024–25.

## Results (second half of each season)

| | 2025–26 | 2024–25 |
|---|---|---|
| Top-20: predicted → actual | 17.90 → 17.17 (**+4%**) | 18.23 → 18.56 (**−2%**) |
| Everyone's mean: predicted → actual | 8.01 → 8.43 | 7.59 → 8.23 |
| Linear correction (a, b) | 1.20 + 0.90·xPTS | 0.97 + 0.95·xPTS |
| RMSE: none → linear | 7.411 → 7.399 | 7.277 → 7.250 |
| Squad points/round: none → isotonic | 149.9 → 146.1 (−3.8 ± 4.8) | 161.1 → 148.9 (−12.2 ± 10.5) |

## Conclusions
- **The overestimation of the top players is not stable:** +4% in one season, −2% in the other. The +7% of 002 was measured on a different pool (only those who played in that round) and doesn't reproduce.
- **Only a small overall «lowering» is stable:** ~0.5 PIR down, for players in the 12. It comes mostly from absences counting in the history, and in live operation it is covered by the availability data.
- **The isotonic correction makes the picks worse** in both seasons, although within the statistical margin.

## Decision
No calibration. The model's numbers stay as they are. The «+7%» of 002 is corrected here as a non-stable finding.
