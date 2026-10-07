# 020 — Participation: how often is the player in the 12?

**Date:** 29/9/2026 · **Status:** ✅ shipped (decision: honest numbers) · 💡 «not on the EuroLeague roster» pending

## Question
A player left out of the 12 doesn't appear in the box score, so the model doesn't see that game. For example, Dessert has 0 appearances this season and the model gives him 4.9 xFPT from last season's mean, which came from 19 appearances in ~38 games.

By minutes played, players with <8 minutes bring 49–60% of the prediction and those with 8–12 minutes 76–82%. But when they dress, they bring ~0.9–1.06 of the prediction. So the gap comes from not dressing, not from playing worse. Test: a participation factor per player multiplies the xFPT.

## Method
- p = (appearances + k · p_position) / (available games + k), with k ∈ {3, 6, 12}.
- **Available games** = his team's games since he arrived, minus absence runs of ≥ S games (S ∈ {2, 3}). A run is almost always an injury. That answers the objection that we don't know who was injured last season: injuries show in the shape of the absences.
- **Season:** this season only, or this season together with last season (last season only if the player is on the same team).
- **A realistic test:** an absence within a run of ≥ S counts as known from day one, as in live operation (the game's list, news). A single absence of a healthy player counts as unknown.
- The variant is chosen on one season by MAE and judged on the other.

## Results

All variants, difference from the model:

| | ΔMAE | Δ squad points |
|---|---|---|
| 2024–25, S=2 | −0.007 to −0.009 | **−73 to −84** |
| 2024–25, S=3 | −0.016 to −0.019 | −19 to +46 |
| 2025–26, S=2 | −0.015 to −0.016 | **−42 to −103** |
| 2025–26, S=3 | −0.027 to −0.029 | **−30 to −129** |

Out of sample:
- **2025–26 (S=3, this season with last season, k=3):** MAE −0.027, squad points **−102**.
- **2024–25 (S=3, this season only, k=12):** MAE −0.016, squad points +19.

## Conclusions
- **The error improves in every variant**, but a little: up to 0.03, at the noise floor.
- **Squad points fall almost everywhere.** The factor mostly lowers the cheap bench players the squad needs as fillers so the expensive ones fit. The optimizer then starts spending credits on «safe» fillers instead of the stars.
- **Last season doesn't help** (this season with last ≈ this season only, or worse). The objection was right.
- As in 010, 017 and 018: the value isn't in a general correction of the xFPT.

## Second round: which reference point, and a run that continues

**Hypothesis:** shrinking towards the position mean also punishes players who haven't shown absences. For example a newcomer to the team, with 1 appearance in 1 game, got 0.82. We tried a reference point of 0.95 and 1.0 («no absences = in the 12»). Squad points didn't change materially, so this hypothesis doesn't explain their fall.

**Final form (live):** this season only, k = 6, p0 = 0.95.
- An injury is only a run of ≥ 3 absences that **ended** with the player's return. A run that continues counts as «out». If the player is injured now, the game's list sets him to 0 anyway.
- A player with no appearance this season gets last season on the same team.

| | ΔMAE | ΔMAE (≥ 12) | Δ squad points |
|---|---|---|---|
| 2024–25 | −0.023 | +0.062 | +26 |
| 2025–26 | **−0.037** | −0.070 | −58 |

## Decision
- **Shipped** (`model.participation`, xFPT × the probability of being in the 12). The owner's decision: the numbers must be honest, and whether to risk a cheap player for the budget is a separate matter. The error improves in both seasons. Squad points move in opposite directions in the two seasons (+26 / −58, about ±2 per round), which is within the noise.
- **Limit:** without an injury list it can't tell «injured for 3 weeks» from «out of the rotation for 3 weeks». Dessert gets 0.85, because his absences last season look like injuries. For such cases the strong signal is another: **he isn't registered on this season's EuroLeague roster** (he exists only in the fantasy list) → the decision on an xFPT of 0 with a «not on the roster» flag is pending.
- An injured player with 1–2 missed games counts as «out» for a few games after his return (e.g. Nebo, 0.71).
- **1/10 (022):** a run of ≥ 3 absences that is still running is left out of the count once the player has appeared for the team again, so it doesn't stack with the return factor of 012(c).
