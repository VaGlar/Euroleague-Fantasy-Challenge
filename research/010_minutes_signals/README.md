# 010 — Where do the minutes go? Teammates' absences, role change, rotation depth

**Date:** 28/9/2026 · **Status:** ❌ the three signals rejected · ✅ side finding: knowing the absences is worth a lot

## Question
009 showed that the missing signal is in each game's minutes. Do three signals, known before the game, explain part of the error?
- **(a) A teammate's absence.** When a starter (15+ minutes per game) is out, his minutes go mostly to the players at his position. Two versions: by position, and without position (in proportion to everyone's minutes).
- **(b) Role change.** He started the last 2 games, while before he started less than 40% of the time (or the reverse). Plus the trend of his minutes (last 2 games vs season).
- **(e) Rotation depth.** How many play 10+ minutes on the team, for players with few minutes.

## Method
- **Target:** the current model's error (real PIR minus prediction), for players who played.
- **Training:** first half of 2025–26. **Test:** second half of 2025–26 and the whole of 2024–25.
- **Budget squad test** (`_lib.squad_points`): both versions *know who is out* (the absentee → 0, as live operation does with injuries and news). One adds the three signals too. That way only the sharing of the minutes is measured, not the knowledge of the absence.
- **Limit:** the absences come from the box score, knowing the outcome. Most are announced before the game, some at the last minute, so the gain of (a) is an upper bound.

## Results

Coefficients (training, ± standard error) and the change in mean error out of sample:

| Signal | Coefficient | ΔMAE 2025–26 2nd half | ΔMAE 2024–25 |
|---|---|---|---|
| (a) same position | **0.13 ± 0.05** | −0.011 | −0.003 |
| (a) other positions | −0.15 ± 0.11 | (together) | (together) |
| (a) no position | 0.02 ± 0.09 | −0.002 | −0.001 |
| (b) became a starter | +0.37 ± 0.46 | −0.012 | −0.007 |
| (b) became a substitute | −0.78 ± 0.52 | (together) | (together) |
| (b) minutes trend | +0.09 ± 0.07 | (together) | (together) |
| (e) rotation depth | −0.06 ± 0.06 | −0.006 | 0.000 |
| **All together** | | **−0.027** | **−0.010** |

Squad points per round, second half of the season (± standard error):

| | 2025–26 | 2024–25 |
|---|---|---|
| Without knowing the absences (current backtest) | 149.9 | 161.1 |
| **Knowing the absences** | **169.1 (+19.2 ± 4.6)** | **171.2 (+10.1 ± 3.2)** |
| + the three signals | 166.1 (−3.0 ± 3.0) | 169.4 (−1.7 ± 4.4) |

In 59% of the rows some starting teammate was out.

## Conclusions
- **(a) Position matters.** The by-position version has the only statistically significant effect, and the version without position none, as intuition said. **But the size is small:** only ~13% of the «expected» extra PIR shows up. An absentee's minutes are shared among many, in ways the positions don't show (big/small line-ups, the coach).
- **(b) The signs are as expected, but not significant.** Role changes are rare (~5% of rows) and have already started to show in the form.
- **(e) No signal.** Rotation depth is already in each player's history (0 minutes count in the form).
- **All together:** −0.01 to −0.03 in mean error, i.e. below the noise floor (0.03). In squad points, slightly negative.
- **Side finding, and the most important one so far:** **knowing who is out** is worth **+10 to +19 points per round** (+7 to +13%). That's more than twice what the model gains over the plain average (~4). It's an upper bound (box score), but it shows where the value is: in the **accuracy and timeliness of availability**, not in the model.

## Decision
- Signals (a), (b), (e) don't go into the model.
- New direction (011): **fresh availability data.** Today the update runs at 07:00 and after the games. Injuries announced during game day don't reach the suggestions before the deadline.
