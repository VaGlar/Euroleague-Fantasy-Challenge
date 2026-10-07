# 009 — The error that remains: noise or a missing signal?

**Date:** 28/9/2026 · **Status:** ✅ diagnostic (leads to experiment 010)

## Why
A critique of 001/002: that a more flexible model or more data improved nothing **doesn't prove the model is right**. It can mean three things:
1. that the model has reached the best possible,
2. that it is too simple (underfitting, high bias),
3. that the data hold no other signal.

We had assumed, without proving it, that the remaining error is «basketball's noise». This checks it.

## Method
2025–26 season, training on rounds 1–19, testing on 20–38 (walk-forward, only players who played):
1. **Training vs test error.** If they are equal and high, the problem is bias or missing information, not overfitting.
2. **Learning curve:** the fit with 5% to 100% of the training rows.
3. **Bounds knowing the outcome** (they can't be used for prediction; they only show what is achievable):
   - (a) each player's real mean over the whole season: the perfect estimate of his «level»,
   - (b) the real PIR per minute × the minutes he really played in that game: what knowing the minutes is worth.

## Results

| | Mean error | RMSE |
|---|---|---|
| Training (in-sample) | 5.360 | 7.156 |
| **Test (out of sample), current model** | **5.283** | **6.965** |
| Test, form only | 5.313 | 6.983 |
| (a) Perfect knowledge of each player's level | 5.024 | 6.641 |
| (b) Perfect knowledge of the level **and the game's minutes** | 4.116 | 5.657 |

Learning curve (test error): 5% → 5.335 · 10% → 5.308 · 25% → 5.293 · 50% → 5.286 · 100% → 5.283.

Spread: around the player's own mean (game to game) **6.6 PIR**. Between players 4.8 PIR.

## Conclusions
- **Not overfitting.** Training and test have the same error.
- **More data of the same kind doesn't help.** The curve flattens after ~25% (~1,100 rows). Together with 002, where gradient boosting didn't help, the obstacle is neither the amount of data nor the model's complexity.
- **It isn't all noise.** The «basketball's noise» assumption was half true:
  - **~5% improvement** (5.28 → 5.02) is the most that's left from a better estimate of each player's level. Of the gap between the plain average (5.43) and that bound, the model has covered about 37%.
  - **~22% improvement** (5.28 → 4.12) would come from knowing the minutes of the specific game. That's where the missing signal is: role, rotation, teammates' absences, fouls.
  - **The rest (~4.1) is genuine performance noise** (shooting percentages etc.), which no model before tip-off catches.
- **Answer to the critique:** a mix of scenarios 2 and 3, with the precision that «2» is about the **features** (information about the specific game), not the model's complexity. Minutes as *averages* (002) didn't help. What's needed is information on *how much he will play in this game*.

## Decision
New experiment **010: teammates' absences.** When a starter is out (injury), his minutes are shared among the others. The information is known before the game (game and news) and live operation already has it. If 010 shows a gain, it's the first real step towards the ~22%.
