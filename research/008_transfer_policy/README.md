# 008 — Trade policy in a whole-season simulation

**Date:** 28/9/2026 · **Status:** ❌ no change needed (the current settings are among the best)

## Question
The trade optimizer's settings were set by reasoning, not by data:
- horizon weights 1 / 0.6 / 0.35 for the current and the next two rounds,
- a minimum gain of +2 per trade,
- up to 4 trades per round.

Are they right?

## Method
- **Each policy plays a whole season**, from round 3 to the end.
- **Start:** the best squad with a budget of 93 credits (100 minus ~7 for the coach).
- **Each round:**
  - the trades the **same optimizer** as live operation would propose (`optimize.transfers`),
  - five, 6th man and captain (`optimize.lineup`),
  - the real fantasy points. A player who didn't play brings 0.
- **Rules:** unlimited changes after rounds 6, 13, 18, 23, 28, 34, as in the game.
- **Predictions** for the current and the next two rounds, only with what was known before each round (`_lib.build_horizon`).
- **Prices** estimated and fixed, as in 004. Two seasons.

## Results: season points total (difference from the current settings ± standard error)

| Policy | 2025–26 (rounds 3–38) | 2024–25 (rounds 3–34) | Trades |
|---|---|---|---|
| **Current** (1/.6/.35, gain 2, 4 trades) | **5,303** | **4,699** | 65 / 51 |
| Next round only | +35 ± 87 | +8 ± 167 | 59 / 59 |
| Flat horizon (1/1/1) | −165 ± 119 | −274 ± 139 | 72 / 72 |
| Longer horizon (1/.8/.6) | −178 ± 96 | −162 ± 118 | 67 / 71 |
| Minimum gain 0 | +59 ± 85 | −38 ± 118 | 81 / 93 |
| Minimum gain 4 | −68 ± 95 | −72 ± 183 | 39 / 40 |
| Minimum gain 6 | **−338 ± 151** | **−329 ± 189** | 27 / 16 |
| Up to 2 trades | **−313 ± 104** | **−268 ± 146** | 45 / 40 |
| No trades (only in the «windows») | **−489 ± 182** | **−590 ± 205** | 0 / 0 |

## Conclusions
- **Trades are worth a lot.** Without them you lose ~500–600 points a season (~10–12%), in both seasons.
- **Use all 4.** A limit of 2 costs ~270–310 points.
- **Strict thresholds cost.** With a minimum gain of 6 you lose ~330 points. Between 0 and 4 the differences are noise. 2 sits in the middle of the good range.
- **A long horizon hurts.** When the next rounds count almost as much as the current one, you lose ~160–270 points, with the same sign in both seasons. Predictions 2–3 weeks out are less reliable (form changes, injuries), and the horizon counts them as certain. The current 1/.6/.35 is statistically no different from «next round only».

## Limits
- Prices don't change. In the game, price changes add value to trading early, before a player rises.
- No turns, no coach, no knowledge of injuries or news: live operation knows them.
- The standard error is large, because the season is one. Only what comes out with the same sign in both seasons counts as reliable.

## Decision
The current settings stay. We don't lengthen the horizon. A slight reduction of the next rounds' weight could be tried this season with the tracking, but the data don't justify it yet.
