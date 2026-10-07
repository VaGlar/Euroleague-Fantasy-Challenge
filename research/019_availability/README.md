# 019 — How accurate is availability?

**Date:** 29/9/2026 · **Status:** ✅ a bug found and fixed · ⏳ the calibration again in 4–5 rounds

## Question
010, 017 and 018 all end up in the same place: the value is in knowing who plays, not in the form blend. The app takes availability from two sources:
- **the game:** `prob_play` / `is_injured`, which give 1, 0.5 or 0 for the player's game,
- **the news:** Gemini's summary gives out / doubtful / questionable.

With both, the round's xFPT is multiplied by the matching factor. How right is all this?

## Method
- For each game played, we take the last `predictions.json` snapshot before tip-off (git history of main, ~4 hours before on average) and compare it with the box score. Each player ends up in one of three categories: played, 0 minutes, not in the box score.
- For the news: in each saved summary, how many of the statuses it wrote were matched to a roster player.

## Results (Round 1: 10 games, 331 players)

**Availability from the game:**

| avail_game | Players | Played | Relevant (xFPT ≥ 8) | Played (relevant) |
|---|---|---|---|---|
| 0 | 17 | 0% | 5 | 0% |
| 0.5 | 16 | 50% | 9 | 67% |
| 1 | 298 | 73% | 105 | 96% |

- **0** is always right: nobody played, so no points were lost.
- **0.5** is well calibrated: half played.
- At **1** there were 4 «surprises» among 105 relevant players (3.8%): Nebo, Leaf, Coffey, D. Washington, with 47.5 xFPT counted while they didn't play. Among the suggestions, Dessert (five in the owner's team) and Akele (bench) didn't play.

**Availability from the news: here was the bug.**
- Gemini often writes the name as «Josh Nebo», while the roster has «NEBO, JOSH». The matching used the exact word order.
- Of the **67** distinct «out / doubtful» statuses in the season's summaries, **only 34** were applied. **33 (49%) were silently ignored**, with no error and no alert.
- Example: Nebo. The summary of 25/9, 15:47 said «out for 2–3 weeks (Gazzetta)», before his game. The model counted him at 14.6 xFPT.

## Decision
- **Fix (shipped):** the names Gemini returns are matched regardless of word order and suffixes (Jr., III). This applies to availability and to the experts' picks. With the fix all 67 statuses are applied.
- A test confirms that an «out» written as «First Last Jr.» sets the player to 0.
- **Limit:** a single round. The calibration (0.5 → 50%, the surprises at 1) needs 4–5 rounds to be judged. `run.py` can be run again at any time.
- **1/10:** the same silent failure in another form: Gemini wrote **every** name in Greek («ΛΕΣΟΡ, ΜΑΘΙΑΣ»), so no injury from the news and no expert pick matched. `news.resolve_names` maps them back to the roster (a sound-alike Latin skeleton, the closest name only when it clearly stands out; 26/26 on the live digest), and the prompt now asks for the roster's Latin names.
