# Αναφορά tester — PR 38 (`claude/festive-babbage-gota28`), 2026-10-08

Mode: **analyze**. Εύρος: το diff του PR έναντι `origin/main` (security headers, φίλτρο συνδέσμων feed, tests από mutation testing).

## 1. Verdict

**Κανένα BLOCKING.** Το σημαντικότερο κενό: ο έλεγχος `safeUrl` στο `web/index.html` δεν τον εκτελεί κανένα test. Μόνο το φίλτρο της Python (`elf/news.py`) ελέγχεται. Επίσης κανένα test δεν επιβεβαιώνει ότι το `_headers` καταλήγει στους φακέλους που κάνουν deploy.

## 2. Κενά (κατά προτεραιότητα)

1. **`safeUrl` χωρίς test** (`web/index.html:496`, χρήση στη γραμμή 754). Μέτριο.
   - Είναι η δεύτερη γραμμή άμυνας: αν ένας σύνδεσμος `javascript:` φτάσει στο `news.json` χωρίς να περάσει από το `collect()`, π.χ. παλιό αρχείο ή χειροκίνητη επεξεργασία, μόνο αυτό τον σταματά.
   - Πρόταση: UI test με fixture `news.json` που περιέχει `javascript:alert(1)`, `" javascript:x"` και `data:text/html,…`. Αναμενόμενο: `href="#"` σε όλα.
2. **Κανένα test ότι το `_headers` γίνεται deploy.** Χαμηλό.
   - Το `update.yml` κάνει `cp -r web/* site/` και το `publish.site()` κάνει `copytree(web)`. Και τα δύο σήμερα αντιγράφουν το `_headers`.
   - Μια μετονομασία, ή ένα `cp` που αφήνει έξω αρχεία με `_`, θα έσβηνε σιωπηλά όλα τα headers.
   - Πρόταση: test που καλεί `publish.site(tmp)` και ελέγχει `(tmp / "_headers").read_text() == web/_headers`, συν έλεγχο ότι το βήμα «Build site» αντιγράφει όλο το `web/`.
3. **Τα headers δεν καλύπτουν τις Pages Functions** (`functions/feed.js`, `functions/api/sync/[[path]].js`). Χαμηλό.
   - Το `_headers` εφαρμόζεται στα στατικά αρχεία. Οι αποκρίσεις των Functions βγαίνουν χωρίς `X-Content-Type-Options` και τα υπόλοιπα, εκτός αν τα βάλει ο ίδιος ο κώδικας.
   - Το επιβεβαιώνει ένα `curl -I` στο live `/api/sync/…`, που δεν το έτρεξα: δεν δοκιμάζω σε production.
4. **`'unsafe-inline'` στο `script-src`.** Χαμηλό, γνωστός συμβιβασμός. Το CSP δεν προστατεύει από XSS μέσω inline script όσο το dashboard έχει inline `<script>`. Η άμυνα σήμερα είναι το `esc()`/`safeUrl()`. Λύση: το script σε ξεχωριστό `.js`, ή nonces/hashes.
5. **XML feeds με `xml.etree.ElementTree.fromstring`** (`elf/news.py:130`, bandit B314). Χαμηλό.
   - Τα feeds είναι τρίτων.
   - Η Python 3.11 με πρόσφατο expat προστατεύει από το «billion laughs». Το `defusedxml` θα έκλεινε το θέμα οριστικά.
   - Δεν αφορά το diff.
6. **CI permissions** (S18). Χαμηλό.
   - Τα `tests.yml`, `lineup.yml` και `deploy-bot.yml` δεν δηλώνουν `permissions:` και παίρνουν το default του repo.
   - Τα third-party actions είναι pinned σε tag, όχι σε SHA.
   - Δεν υπάρχει `.github/CODEOWNERS` για το `.github/workflows/`.
7. **Δεν υπάρχει `TESTING.md`.** Χωρίς αυτό δεν υπάρχει όριο mutation score, ούτε επίσημη λίστα «κρίσιμων αρχείων». Πρόταση: να γραφτεί, με κρίσιμα τα `optimize.py`, `lineup_cmd.py`, `publish.py` και `validate.py`.

## 3. Tests που προστέθηκαν

Κανένα σε αυτό το run (analyze). Τα tests του PR, γραμμένα πριν από αυτό το run, αξιολογήθηκαν παρακάτω.

## 4. Εύρος tests (F1–F15)

- **F1:** καλύπτεται. Το diff-cover δίνει 100% στις αλλαγμένες γραμμές Python (`elf/news.py`). Τα HTML/`_headers` δεν μετριούνται από το coverage.
- **F2:** μερικώς.
  - Υπάρχουν boundary tests για το `PLAN_MIN_X`, το threshold των trades και τα 4 trades.
  - Λείπουν τα όρια του `validate` (200 παίκτες, 16–22 ομάδες, τιμές 1–40). Είναι αυθαίρετα, χαρακτηρισμένα ως equivalent παρακάτω.
- **F3:** καλύπτεται. Καλύπτονται το 4xx από το παιχνίδι, το NaN, τα χαλασμένα αρχεία, το stale nonce και ο μη έγκυρος σύνδεσμος feed.
- **F4:** ναι. Το `test_collect_keeps_only_web_links` αποτυγχάνει στον παλιό κώδικα, και το επιβεβαίωσα.
- **F7:** το `_expected_shortfall` ελέγχεται απέναντι σε αριθμητική ολοκλήρωση. Αυτή είναι ανεξάρτητη αναφορά, όχι η έξοδος του κώδικα.
- **F9:** λείπει. Δεν υπάρχουν property-based tests, π.χ. με `hypothesis` για τα `safeUrl`, `esc` και `normalize_player`.
- **F10:** υπάρχει (Playwright, και οι δύο εκδόσεις). Τα tests τρέχουν πλέον με τα πραγματικά headers του `_headers`.
- **F14:**
  - mutmut 3.8.0 στα 4 κρίσιμα modules: πριν το PR **1726/2184 (79%)**, μετά **2106/2184 (96%)**.
  - Από τους 78 που επιζούν όλοι είναι **equivalent ή χωρίς αξία**: κείμενα μηνυμάτων, μορφοποίηση JSON (`indent`, `ensure_ascii`), ±1 σε αυθαίρετα όρια του `validate`, όνομα του LP problem, default `max_trades=4→5`.
  - Επιβεβαίωσα ότι τα tests περνούν μέσα στο `mutants/` χωρίς mutation, άρα τα «kills» δεν είναι ψεύτικα.
- **F15:** καμία αστάθεια στα 2 πλήρη runs (340 passed).
- **F5, F6, F8, F11, F12, F13:** δεν τα αγγίζει το diff. Βλ. πίνακα.

## 5. Πίνακας εφαρμοσιμότητας

| ID | Status | Τεκμήριο / λόγος | Αποτέλεσμα |
|----|--------|------------------|------------|
| F1 | RUN | diff-cover vs origin/main | 100% στις αλλαγμένες γραμμές Python |
| F2 | RUN | review | μερικώς (βλ. §4) |
| F3 | RUN | review | καλύπτεται |
| F4 | RUN | bugfix στο `news.py` | regression test υπάρχει |
| F5 | RUN | fake game / fake feeds στα όρια | καλύπτεται (το FakeGame ελέγχει πλέον τα ids) |
| F6 | N/A | `HTTP_API` εκτός diff (`functions/api/sync`) | — |
| F7 | RUN | `CALCULATIONS` (optimizer) | shortfall έναντι ολοκλήρωσης |
| F8 | N/A | το diff δεν αγγίζει retries/concurrency | — |
| F9 | RUN | pure functions υπάρχουν | λείπει (κενό, χαμηλό) |
| F10 | RUN | Playwright | τοπικά πράσινο με headers (από προηγούμενο run) |
| F11 | N/A | `DB_MIGRATIONS` όχι στο diff (D1 μόνο στο sync) | — |
| F12 | RUN | `RUN_URL` απών/παρών, `TELEGRAM_BOT_TOKEN` | καλύπτεται |
| F13 | N/A | το diff δεν αλλάζει βρόχους σε μεγάλα δεδομένα | — |
| F14 | RUN | mutmut 3.8.0 | 96%, 78 equivalent |
| F15 | RUN | 2 πλήρη runs | χωρίς flaky |
| S01 | RUN | regex σάρωση ιστορικού και diff (gitleaks/trufflehog μη διαθέσιμα) | τίποτα. Σημείωση: regex ≠ gitleaks |
| S02 | RUN | `pip-audit -r requirements.txt` | no known vulnerabilities. Το `npm audit` στο `tests/ui` δεν έτρεξε |
| S03 | N/A | το diff δεν αγγίζει auth/sync. Το access του personal site το κάνει το Cloudflare Access | — |
| S04 | RUN | `web/_headers` | headers υπάρχουν. Κενά 3–4 |
| S05 | N/A | το diff δεν αγγίζει crypto. Το SHA1 (B324) στο `lineup_cmd` είναι αναγνωριστικό πρότασης, όχι ασφάλεια | — |
| S06 | RUN | XSS στον σύνδεσμο feed | διορθώθηκε στην Python (με test) και στο JS (χωρίς test, κενό 1) |
| S07 | CANNOT_CHECK | rate limit του `/api/sync` εκτός diff, θέλει live app | γνωστό ανοιχτό θέμα |
| S08 | N/A | `AUTH` μέσω Cloudflare Access, εκτός repo | — |
| S09 | RUN | third-party scripts/fonts | Cloudflare beacon και Google Fonts χωρίς SRI (CF Analytics: δεν υποστηρίζει SRI) |
| S10 | RUN | review | το `validate` στέλνει προβλήματα, όχι προσωπικά δεδομένα. Οκ |
| S11 | RUN | review | fail closed: το NaN σταματά το publish, το 4xx σταματά το apply |
| S12 | N/A | `FILE_IO` μόνο σε σταθερά paths του repo | — |
| S13 | N/A | `HTTP_API` εκτός diff | — |
| S14 | CANNOT_CHECK | το `functions/feed.js` είναι proxy URL, εκτός diff, χωρίς τοπικό runtime | να ελεγχθεί σε ξεχωριστό run |
| S15 | RUN | DOM XSS στο `index.html` | ένας sink (`href`) με `safeUrl`. Χωρίς test |
| S16 | N/A | το LLM (σύνοψη ειδήσεων) εκτός diff | — |
| S17 | N/A | το diff δεν αγγίζει προσωπικά δεδομένα | — |
| S18 | RUN | workflows | κενό 6 |

## 6. Προφίλ project

- **Γλώσσες:**
  - Python 3.11 (`elf/`),
  - vanilla JS (`web/`),
  - Cloudflare Worker και Pages Functions (`worker/`, `functions/`).
- **Tests και εργαλεία:**
  - pytest + pytest-cov (`.coveragerc`, `fail_under = 90`),
  - Playwright (`tests/ui/`),
  - node runner για τον Worker,
  - mutmut 3.8.0 μόνο τοπικά.
- **Flags:**

  | Flag | Τιμή | Τεκμήριο |
  |---|---|---|
  | `WEB_UI` | ναι | `web/index.html` |
  | `HTTP_API` | ναι | `functions/api/sync` |
  | `AUTH` | εξωτερικό | Cloudflare Access |
  | `DB_SQL` | ναι | D1 στο sync |
  | `EXTERNAL_HTTP` | ναι | `functions/feed.js`, `elf/news.py` |
  | `SECRETS_USED` | ναι | workflows |
  | `PERSONAL_DATA` | ελάχιστα | ομάδα του ιδιοκτήτη στο `elf-data` |
  | `LLM_FEATURES` | ναι | σύνοψη ειδήσεων |
  | `CLI_OR_SCRIPT` | ναι | |
  | `DATA_PIPELINE` | ναι | |
  | `CALCULATIONS` | ναι | `optimize.py` |
  | `DEPLOYED_PUBLIC` | ναι | Pages |
  | `DEPENDENCIES` | ναι | |
  | `CI` | ναι | |
  | `PAYMENTS` | όχι ακόμα | |
  | `FILE_UPLOAD` | όχι | |
  | `BAAS` | όχι | |
  | `DB_MIGRATIONS` | UNKNOWN | D1 schema στο sync |

- **Spec:** δεν υπάρχει `TESTING.md`, `SPEC.md` ή `CLAUDE.md`. Οι κανόνες για τα δημόσια/ιδιωτικά δεδομένα είναι στο README.

## 7. Παραδοχές και όρια

- Οι αυτόματοι και στατικοί έλεγχοι **δεν αποδεικνύουν ασφάλεια και δεν είναι penetration test**.
- **Δεν ελέγχθηκαν:**
  - τα live headers και οι Functions σε production (κανόνας: όχι δοκιμές σε production),
  - `npm audit` στα `tests/ui` και `worker`,
  - gitleaks/trufflehog (δεν ήταν εγκατεστημένα· έγινε μόνο regex σάρωση).
- Το UI run με τα headers είναι από προηγούμενο τοπικό run πριν το τελευταίο commit. Το τελευταίο commit αλλάζει μόνο Python tests.
- **Εκδόσεις:**
  - εργαλεία: pytest 9.1.1, mutmut 3.8.0, pip-audit, bandit και diff-cover (τελευταίες από PyPI στις 2026-10-08),
  - πρότυπα αναφοράς: OWASP Top 10:2025, ASVS 5.0.0, WSTG 4.2. Δεν επαλήθευσα online αν υπάρχουν νεότερες εκδόσεις, και δεν ανέφερα αριθμούς ASVS από μνήμης.
