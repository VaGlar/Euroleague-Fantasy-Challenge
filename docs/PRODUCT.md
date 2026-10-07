# Public edition — product plan

A public analysis app for EuroLeague fantasy basketball: a daily report, news, stats,
team analysis and a personal assistant for each user's team (five, captain, Turns, trades).

The repository holds **one** engine with **two editions**: the personal one (the existing system)
and the public one. Only results are published. The repository itself went public in October 2026;
the owner's data and the article archive live in a private data repo (see the README, «Public repo
and private data»).

> Product name: **HoopsLab** (beta). The name does **not** contain the word «EuroLeague» nor
> the competition's logos (see «Legal and tax»). The product speaks Greek: its audience is
> Greek-speaking managers.

---

## 1. Vision and value

- The product's value lies in **analysis and aggregated stats**, not in «magic»
  predictions. The model is demonstrably better than a plain average (backtest
  2025-26: mean error 5.33 vs 5.43 PIR), but the improvement is small; the product's
  messaging must be equally modest.
- The app publicly measures its own accuracy per round (the «Μοντέλο» tab). That transparency
  is part of the value.

## 2. Editions

| | Personal edition (existing system) | Public edition |
|---|---|---|
| Team | Read automatically from the game | Entered **by hand** by the user |
| Changes in the game (`/lineup`) | Yes | **No** — the user makes the changes in the game |
| Telegram | Yes | No (in the first phase) |
| Report, news, players, teams, compare, model | Yes | Yes |
| Five, captain, Turn plan, trades | Yes | Yes, computed in the user's browser |
| Devices in step | — (the team comes from the game) | Yes, with a sync code (Cloudflare D1) |

When users make trades or changes in the game, they record them in the app too
(«replace player», «who is in the five»).

## 3. Business model

- **Rounds 1–10: free for everyone**, no account.
- **From round 11: access by signing in with Patreon** (an active membership).
  - Members with an active membership are approved automatically; an **exceptions list** (e.g. the
    group's admins, partners) is controlled by the admin only.
  - The admin can revoke access at any time.
- **To decide:** what stays free after round 10. Proposal: the report and news
  free; «Η ομάδα μου» (my team), compare and trades for members.
- A partnership with the admins of the «EuroLeague Fantasy Greece» group is suggested
  (e.g. a share or free access), rather than a plain post.
- A realistic estimate: out of 70,000 members, 2,000–5,000 users and 1–5% paying members.

## 4. Architecture

```
                 one run (10:05 + after the games) — elf/run.py
   EuroLeague data + prices (dedicated account) + news + Gemini + model
                  │                                        │
        shared results                             personal part
  (report, news, players, teams,             (my team, /lineup, Telegram,
   compare, model)                            personal token, lineup logs)
                  │                                        │
   elf/publish.py: allow-list of files,        data/public as it is
   personal fields removed                                │
                  │                                        │
   public site (Cloudflare Pages)             personal dashboard + bot
   • team entered by hand, optimizer           (behind Cloudflare Access)
     in the browser (web/opt.js)
   • devices in step: Pages Function + D1
   • from round 11: Worker with
     Patreon sign-in, exceptions list, D1
```

**Why one engine:** every fix applies to both editions at once, the same tests
protect them, and one run serves both (half the Actions minutes, one price read, one Gemini
call). The predictions are the same, so the public accuracy measurement also covers the product.

**Why compute in the browser:** each user's personal computation runs on their device;
no per-user server is needed and the cost stays at zero up to a few thousand users.

### Splitting the editions (done)
- `elf/publish.py`: an **allow-list** of files for the public (`PUBLIC_FILES`); anything not listed
  is never copied, so a new personal file can't leak by mistake.
  Removed: my team, the operational notes (token, account), the lineup logs.
- `report_public.json`: the same report without the personal parts (five, trades, captain
  of my team) — published as `report.json`.
- A test (`test_public_edition_has_nothing_personal`) that fails if anything personal
  leaks; checked to catch a deliberate leak.
- Workflow: the «Deploy public edition» step stays **off** until the `PUBLIC_PROJECT` variable
  (the Cloudflare Pages project name) is set; optionally `PUBLIC_URL` for the link
  in the report.

### Storing the team (free period)
- Stored locally on the device, with an «Add to Home Screen» prompt.
  **Important:** Safari deletes a site's data after 7 days without use,
  unless the app was added to the home screen.
- A **backup code/link** (e.g. `…/#t=A7K2…`): restores the team on
  any device, with no account and no personal data.
- **Devices in step (done):** a sync code keeps a PC and a phone on the same team (Cloudflare D1,
  `functions/api/sync`). The table has a `user_id` column for when accounts come.
- After Patreon sign-in: the team is stored on the server too (Cloudflare D1).

### Data updates (done)
- **07:05** every day, **3 hours before the first game** of each game day (fresh injuries before the deadline) and **~2.5 hours after the last game** of each game day (results,
  real points, accuracy measurement). Every run updates both editions.
- The timing comes from a Cloudflare cron (GitHub's scheduled runs are hours late).
- Errors (e.g. Gemini, news sources, the token) are **not** shown in the public edition; the
  admin is notified on Telegram, only when the state changes.

### Installing on a phone (done)
- The name **HoopsLab** (beta) in the public edition, a PNG icon for the Home Screen.
- A pop-up «Βάλ' το στην οθόνη σου» (put it on your screen) guide for iPhone/Android on the first visit.

### Free-tier limits (indicative — to be confirmed before launch)
| Service | Limit | Estimated use |
|---|---|---|
| Cloudflare Pages | static files, practically unlimited | — |
| Cloudflare Workers / Functions | 100,000 requests/day | ~5 per active user/day |
| Cloudflare D1 | 5 GB, 5M reads/day, ~100k writes/day | small |
| GitHub Actions | free for a public repo | — |
| Gemini (free tier) | per minute/day | 1 summary per run, shared by all |

## 5. Data sources and risks

- **EuroLeague** (public APIs): games, box scores, rosters, news.
- **Fantasy prices (Dunkest):** need a token (confirmed: `401 Unauthenticated` without one).
  - **Only a dedicated account** is used, not the personal one.
  - One read per day.
  - Fallback: users can enter or correct the price of their own players.
- **News / fantasy columns:** RSS and public pages; summarized with Gemini.
- Risk: the unofficial APIs can change or be restricted without notice. Source health
  is shown in the app («Κατάσταση»).

## 6. Security

> **Fantasy tokens rule:** each account stays signed in in its own browser; **never log out**
> after copying the token (logging out revokes it). Sign-in goes through a shared login
> site, so two accounts in the same browser «get mixed up».

- [x] Private data in a **private** data repo (`elf-data`); the code repo is public and sanitized,
      with a test that fails on anything personal (`tests/test_public_repo.py`).
- [ ] Personal dashboard behind **Cloudflare Access** (free up to 50 users; access only with the admin's email). **Before HoopsLab opens to the public:** `elf-dashboard.pages.dev` is open to anyone with the link today (team, suggestions, `predictions.json` with `my_team`). The bot needs a service token first, so the Worker can read the data behind Access.
- [ ] **2FA** on GitHub, Cloudflare, Patreon, Google (Gemini).
- [ ] Tokens with **least privilege and an expiry** (GitHub fine-grained, Cloudflare
      scoped). Prices are read with the **dedicated account's** token (secret `FANTASY_DATA_TOKEN`); the
      personal token (`FANTASY_TOKEN`) only for the personal edition (`/lineup`, reading the team).
      Without `FANTASY_DATA_TOKEN` prices are read with the personal one for now.
- [x] **`main` protected**: changes only through a pull request with passing tests.
- [ ] **Secret scanning**, **Dependabot**, GitHub Actions pinned to a specific version (SHA).
- [x] Publishing allow-list + leak test (`elf/publish.py`).
- [ ] Worker: **rate limiting**, origin checks, signed session cookies; **no
      password** is ever stored (sign-in through Patreon only).
- [ ] Protected data only through a Worker after a membership check (a lock in the
      app alone is easy to bypass).
- [ ] Minimal personal data; a **privacy policy** (GDPR) before sign-ins are turned on.

## 6a. Analytics

Every morning at 09:05 the Worker starts `analytics.yml` → `elf/analytics.py`: it sends to Telegram yesterday's visits/views per site, the week vs the previous one, and for HoopsLab the countries, devices and referrers. Needs Cloudflare Web Analytics on the Pages projects and the `CF_ANALYTICS_TOKEN` secret (an API token with *Account Analytics: Read* only).

## 7. Legal and tax

> The notes below are not legal or tax advice; an accountant must confirm them
> before memberships start.

- **Patreon** collects the payments and, as a rule, the VAT for members
  in the EU. It does **not** cover income tax in Greece; registering as self-employed
  is probably required.
- Check the **terms of use** of Dunkest and EuroLeague for commercial use of the data.
- Name and artwork **without** EuroLeague trademarks; an explicit statement that the app is
  unofficial and not affiliated with the competition.

## 8. Phases

| Phase | Content | Status |
|---|---|---|
| 0. Infrastructure & security | ✅ split editions (publish + test) · ✅ dedicated fantasy account (`FANTASY_DATA_TOKEN`, in its own browser) · ✅ public code repo + private data repo · ✅ `main` protected · Cloudflare Access · 2FA | in progress |
| 1. Public app (MVP) | ✅ team entered by hand (search, prices, credits) · ✅ stored on the device + backup link · ✅ «five as in the game» · ✅ optimizer in the browser (`web/opt.js`, checked against Python) · ✅ «✓ Το έκανα» (done) on trades · ✅ `PUBLIC_PROJECT` on · ✅ the new «Η ομάδα μου» (`web/team.js` v2): set-up on an empty court, the «To do» list (trades → five → captain, counting the trades made), drag players to swap places with auto-scroll, player sheet with actions, ⋯ menu · ✅ the same screen in the personal edition (team from the game, trades from Python, applied with /lineup) · ✅ ✕ as in the game (take players off, fill the places) · ✅ devices in step (sync code, D1) | done |
| 2. Closed beta | 20–50 members of the group for 1–2 rounds | — |
| 3. Public launch | Announcement in the group | — |
| 4. Memberships | Patreon sign-in, exceptions list, team stored on the server, privacy policy — **before round 10** | — |

**Timeline:** every week of delay shortens the free period (e.g. a launch in round 4
means 6–7 free rounds).

## 9. Open decisions

1. The final product name.
2. What stays free after round 10.
3. Price and tiers of the Patreon membership.
4. The partnership with the group's admins.
5. Notifications (e.g. a public Telegram channel or web push) in a later phase.
6. **`/ρωτα` (ask) over the article history (personal edition only) — on hold.** The article archive is already being collected
   (`archive/`, in the private data repo). If it happens: a name/date filter first, embeddings later in a plain file
   (not ChromaDB), run like `/lineup` (Worker → GitHub Action → Telegram). The daily summary **stays as it is**:
   it reads only 4–7 days (~3% of the context) and availability needs all recent articles, not a top-k.
   Limit: for non-fantasy sources we keep only 600 characters per article.
7. **Choosing a language at the start (next step).** On the first visit the user picks a language (Ελληνικά / English),
   changeable later in the settings. Needs: every text of the page (`web/index.html`, `web/team.js`) in a
   dictionary per language, the ⓘ explanations, the install guide and the news summary (Gemini writes it in
   Greek today: a second version or a translation). The game's terms (Credits, Trades, CAP, xFPT…) stay the same.

---

Technical instructions (setup, commands, secrets): see the main `README.md`.
