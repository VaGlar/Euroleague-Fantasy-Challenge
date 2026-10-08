# Αναφορά tester — PR 38 (`claude/festive-babbage-gota28`), 2026-10-08

**Modes:**
- analyze για το diff του PR 38 και πλήρες baseline του `functions/api/sync`·
- write-tests για 3 tests του `validate`·
- ci-maintenance για το gitleaks στο `tests.yml`.

Τα outputs όλων των εντολών βρίσκονται στον φάκελο [`2026-10-08-claude-festive-babbage-gota28-appendix/`](2026-10-08-claude-festive-babbage-gota28-appendix/), αρχεία 00–06.

## 1. Verdict

**Κανένα BLOCKING.** Το σημαντικότερο κενό είναι εύρημα του baseline του sync και αφορά τους χρήστες: ένας κωδικός συγχρονισμού γραμμένος με **ελληνικό πληκτρολόγιο** απορρίπτεται. Τα Α, Β, Ε, Η, Κ, Μ, Ν, Ρ, Τ, Υ, Χ, Ζ μοιάζουν με λατινικά αλλά πετιούνται.

## 2. Κενά (κατά προτεραιότητα)

1. **Κωδικός sync με ελληνικά γράμματα** (`web/team.js:146`, `functions/api/sync/[[path]].js` στο `cleanCode`). **Μέτριο, bug χρηστικότητας.**
   - Το `toUpperCase().replace(/[^A-Z0-9]/g, "")` κρατά μόνο λατινικά.
   - Το ελληνικό «Α» (U+0391) είναι οπτικά ίδιο με το «A», αλλά αφαιρείται. Ο κωδικός βγαίνει μικρότερος από 12 χαρακτήρες και η σελίδα λέει «μη έγκυρος».
   - 12 από τα 23 γράμματα του `ALPHABET` έχουν ελληνικό δίδυμο, οπότε σχεδόν κάθε κωδικός γραμμένος με το χέρι αποτυγχάνει.
   - Τεκμήριο: appendix 04, `cleanCode("ΑΒΓ") → ""`.
   - Fix (developer): αντιστοίχιση ΑΒΕΗΚΜΝΡΤΥΧΖ → ABEHKMNPTYXZ πριν το φιλτράρισμα, και στον client και στον server. Test: `syncJoin`/`cleanCode` με κωδικό γραμμένο σε ελληνικά.
2. **Τα headers δεν καλύπτουν τις Pages Functions. Επιβεβαιωμένο.** Χαμηλό–μέτριο.
   - Η τεκμηρίωση του Cloudflare το λέει ρητά (appendix 02).
   - Στο live, το `/api/sync` απαντά μόνο με `content-type` και `cache-control`, χωρίς ούτε τα default `nosniff`/`referrer-policy` που το Pages βάζει στα στατικά.
   - Fix (developer): τα headers μέσα στο `json()` του sync και στο `functions/feed.js`, ή ένα `functions/_middleware.js`.
   - Μετά το merge να ξανατρέξει το `curl -I`: το PR 38 δεν έχει γίνει deploy ακόμα, οπότε το live δείχνει ακόμα τα defaults.
3. **Ο server αποθηκεύει οποιοδήποτε `roles`, και ο client το τυπώνει χωρίς `esc()`** (`web/team.js:602`, `617`). **Μέτριο, λανθάνον.**
   - Ο server δέχεται `roles` με HTML: `201` (appendix 04).
   - **Το XSS δεν αναπαράχθηκε** (appendix 06): ένας παίκτης με άγνωστο role δεν παίρνει chip, και το sheet ανοίγει μόνο από chip.
   - Μια μελλοντική λίστα με όλους τους παίκτες θα το έκανε προσβάσιμο, με κοινόχρηστο κωδικό ως φορέα. Το CSP επιτρέπει inline handlers (`'unsafe-inline'`) και `img-src https:`, άρα και διαρροή δεδομένων.
   - Fix (developer): `esc(role)` στα δύο σημεία, και στο `validTeam` τα `roles` να περιορίζονται σε `5άδα/6ος/πάγκος/coach`.
4. **`safeUrl` χωρίς test** (`web/index.html:496`). Χαμηλό. Πρόταση: UI test με fixture που έχει `javascript:`/`data:` και αναμένει `href="#"`.
5. **Κανένα test ότι το `_headers` φτάνει στο deploy** (`update.yml` «Build site», `publish.site`). Χαμηλό.
6. **Sync: δεν υπάρχει rate limit στο `POST`, ούτε όριο στο πλήθος ή στη διάρκεια ζωής των εγγραφών** (S07/S17). Χαμηλό.
   - Αυτόματα POST μπορούν να γεμίζουν το D1.
   - Δεν υπάρχει τρόπος διαγραφής (`DELETE` → 405). Δεν αφορά προσωπικά δεδομένα με την τωρινή μορφή, γιατί το `user_id` μένει κενό. Θα αφορά όταν έρθουν λογαριασμοί.
7. **Sync: το `MAX_BYTES` μετράει χαρακτήρες UTF-16, όχι bytes.** 150.000 ελληνικοί χαρακτήρες δίνουν 300 KB και γίνονται δεκτοί (appendix 04). Χαμηλό.
8. **Το `'unsafe-inline'` στο CSP**, το **XML χωρίς `defusedxml`** (`elf/news.py:130`), και στο **CI τα actions pinned σε tag αντί για SHA** και η έλλειψη `CODEOWNERS`. Όλα χαμηλά, αμετάβλητα από την προηγούμενη αναφορά.
9. **Δεν υπάρχει `TESTING.md`**: λείπει όριο για το mutation score.

Τι **δουλεύει σωστά** στο sync (appendix 04):
- όλα τα SQL έχουν bound parameters, και ο κωδικός «`' OR 1=1--`» απορρίπτεται με 400·
- το race μεταξύ δύο συσκευών δίνει 409 με το αποθηκευμένο αντίγραφο·
- τρεις διαδοχικές συγκρούσεις κωδικών δίνουν 500, το όριο των 15 παικτών είναι σωστό (15 → 201, 16 → 400), και χωρίς D1 η απάντηση είναι 503·
- η απάντηση δεν περιέχει `user_id` (S13)·
- ο κωδικός έχει 59,43 bits εντροπίας. Το modulo bias (`x % 31`) κάνει τα A–H περίπου 8% πιο συχνά, χωρίς πρακτική σημασία.

## 3. Tests που προστέθηκαν

| Αρχείο | Test | Τι ελέγχει | Πηγή αναμενόμενων τιμών |
|---|---|---|---|
| `tests/test_validate.py` | `test_a_few_odd_players_do_not_stop_the_update` | ένας παίκτης χωρίς xFPT και μία τιμή εκτός 1–40 δεν σταματούν το update | docstring του `validate.py` («unusable» vs «smaller oddities») |
| `tests/test_validate.py` | `test_report_message_without_text_stops` | μήνυμα report χωρίς `text` σταματά το update | ίδιο docstring και το μήνυμα του κώδικα |

Και τα δύο πιάνουν τους mutants 128, 154 και 188, όπως επαληθεύτηκε με το χέρι (appendix 03).

**CI:**
- νέο job `secrets` στο `tests.yml`: gitleaks 8.27.2 με επαλήθευση sha256, `--redact`. Στα PRs σαρώνει μόνο τα commits του PR. Ένα χειροκίνητο run σαρώνει όλο το ιστορικό.
- `permissions: contents: read` στο workflow.
- Τοπική δοκιμή του ίδιου script (appendix 05): σε αυτό το PR δεν βρίσκει leaks. Σε ψεύτικο token αποτυγχάνει με exit 1 και δείχνει την τιμή ως `REDACTED`.
- Full history baseline: 321 commits, **κανένα leak** (appendix 01).

## 4. Εύρος tests (F1–F15)

- **F1:** τα tests περνούν (342 passed), coverage 91,52%. Το diff-cover δίνει 100% στις αλλαγμένες γραμμές Python.
- **F2:** ελέγχονται τα όρια του optimizer και τα 15/16 του sync (μόνο ως probe, όχι στη σουίτα).
- **F3, F4, F5:** καλύπτονται.
- **F6:** το sync έχει 2 tests· το baseline βρήκε περιπτώσεις χωρίς test: 405 σε DELETE, PUT με χαλασμένο JSON σε υπάρχοντα κωδικό, το race (`UPDATE` χωρίς αλλαγές), 3 συγκρούσεις κωδικών, όριο 15/16 και επικύρωση των `roles`.
- **F7:** ελέγχεται.
- **F8:** το race του sync ελέγχθηκε με probe. Λείπει test στη σουίτα.
- **F9:** λείπει.
- **F10:** ελέγχεται.
- **F14:**
  - 96% (2106/2184).
  - Από τους 78 επιζώντες, 10 ελέγχθηκαν με το χέρι: 3 πραγματικά κενά (κλειστά πλέον) και 7 equivalent (appendix 03).
  - Οι υπόλοιποι 68 ανήκουν στις ίδιες κατηγορίες equivalent.
- **F15:** καμία αστάθεια.

## 5. Πίνακας εφαρμοσιμότητας

| ID | Status | Τεκμήριο / λόγος | Αποτέλεσμα |
|----|--------|------------------|------------|
| F1 | RUN | pytest + diff-cover (appendix 00) | 342 passed, 100% στις αλλαγμένες γραμμές |
| F2 | RUN | review + sync probe | μερικώς |
| F3 | RUN | review + sync probe | καλύπτεται |
| F4 | RUN | bugfix στο `news.py` | regression test υπάρχει |
| F5 | RUN | FakeGame, fake D1 | καλύπτεται |
| F6 | RUN | `HTTP_API` (sync) | contract σωστό· 6 περιπτώσεις χωρίς test (§4) |
| F7 | RUN | `CALCULATIONS` | shortfall έναντι ολοκλήρωσης |
| F8 | RUN | το sync έχει optimistic locking | σωστό στο probe· χωρίς test |
| F9 | RUN | pure functions | λείπει |
| F10 | RUN | Playwright | πράσινο (προηγούμενο run)· probe XSS με τα headers του `_headers` |
| F11 | CANNOT_CHECK | D1 `CREATE TABLE IF NOT EXISTS` χωρίς migrations· χωρίς πρόσβαση στο live D1 | — |
| F12 | RUN | `RUN_URL`, `TELEGRAM_BOT_TOKEN`, `SYNC_DB` | καλύπτεται (503 χωρίς binding) |
| F13 | RUN | `MAX_BYTES` | κενό 7 |
| F14 | RUN | mutmut + χειροκίνητος έλεγχος | 96%· appendix 03 |
| F15 | RUN | 3 πλήρη runs | χωρίς flaky |
| S01 | RUN | gitleaks 8.27.2, όλο το ιστορικό | κανένα leak· πλέον στο CI |
| S02 | RUN | pip-audit | καθαρό· το `npm audit` δεν έτρεξε |
| S03 | RUN | sync: ο κωδικός είναι το κλειδί, χωρίς λογαριασμούς | εκ σχεδιασμού όποιος έχει τον κωδικό γράφει· 59 bits |
| S04 | RUN | `curl -I` στο live + docs | κενό 2 (επιβεβαιωμένο) |
| S05 | RUN | `crypto.getRandomValues` στο sync | σωστό· μικρό modulo bias |
| S06 | RUN | SQL (sync), XSS (news, roles) | SQL ασφαλές· XSS: κενά 3–4 |
| S07 | RUN | sync POST | κενό 6 |
| S08 | N/A | `AUTH` μέσω Cloudflare Access (τεκμήριο: 302 με `www-authenticate: Cloudflare-Access`, appendix 02) | — |
| S09 | RUN | third-party scripts | CF beacon/Fonts χωρίς SRI |
| S10 | RUN | review | οκ |
| S11 | RUN | sync: 400/404/405/409/413/500/503, όλα JSON χωρίς stack | οκ |
| S12 | N/A | `FILE_IO` μόνο σε σταθερά paths | — |
| S13 | RUN | απάντηση του sync | χωρίς `user_id` ή εσωτερικά πεδία |
| S14 | CANNOT_CHECK | `functions/feed.js` (proxy URL) εκτός του εύρους που ζητήθηκε | επόμενο baseline |
| S15 | RUN | DOM XSS | κενά 3–4 |
| S16 | N/A | LLM εκτός diff | — |
| S17 | RUN | διάρκεια ζωής εγγραφών του sync | κενό 6· για ανθρώπινη αξιολόγηση όταν έρθουν λογαριασμοί |
| S18 | RUN | workflows | `contents: read` στο `tests.yml`· pinned tags· χωρίς CODEOWNERS |

## 6. Προφίλ project

Αμετάβλητο από το πρώτο run της ημέρας:
- Python 3.11 (`elf/`), vanilla JS (`web/`), Cloudflare Worker/Pages Functions με D1·
- pytest + pytest-cov (`fail_under = 90`), Playwright, node runners, mutmut 3.8.0 (τοπικά)·
- δεν υπάρχει `TESTING.md`.

Σημαντικά flags:

| Flag | Τιμή | Τεκμήριο |
|---|---|---|
| `HTTP_API` | ναι | `/api/sync` |
| `DB_SQL` | ναι | D1 |
| `AUTH` | εξωτερικό | Cloudflare Access μόνο στο personal site |
| `DEPLOYED_PUBLIC` | ναι | `hoopslab-beta.pages.dev` |

## 7. Παραδοχές και όρια

- Οι αυτόματοι και στατικοί έλεγχοι **δεν αποδεικνύουν ασφάλεια και δεν είναι penetration test**.
- Στο live έγιναν μόνο αιτήματα `HEAD`, χωρίς επίθεση. Το sync δοκιμάστηκε τοπικά σε fake D1, όχι στο πραγματικό D1.
- **Δεν ελέγχθηκαν:**
  - η συμπεριφορά του Cloudflare στο URL-decoding των params (στο appendix 04 η περίπτωση «με κενά» είναι τεχνούργημα του harness)·
  - `npm audit`·
  - S14 (`feed.js`)·
  - τα headers του PR 38 στο live, γιατί δεν έχει γίνει deploy ακόμα.
- Το gitleaks 8.28.0 έδωσε 502 κατά το download. Χρησιμοποιήθηκε το 8.27.2, με επαληθευμένο checksum.
- **Εκδόσεις:**
  - εργαλεία: pytest 9.1.1, mutmut 3.8.0, gitleaks 8.27.2, pip-audit, bandit, diff-cover (PyPI, 2026-10-08), Playwright από `tests/ui/package-lock.json`·
  - πρότυπα αναφοράς: OWASP Top 10:2025, ASVS 5.0.0, WSTG 4.2. Δεν επαληθεύτηκαν online για νεότερες εκδόσεις.
