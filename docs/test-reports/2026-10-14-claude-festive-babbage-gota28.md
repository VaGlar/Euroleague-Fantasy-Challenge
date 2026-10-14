# Αναφορά tester: PRs 39–44 του developer (2026-10-14)

**Mode:** analyze + write-tests.

**Εύρος:** ό,τι έγινε merge στο `main` μετά το PR 38 (`de7895b..d4cb34f`). Έμφαση σε όσα γράφουν στο παιχνίδι ή εκθέτουν endpoint:
- `elf/lineup_cmd.py` (PR 40, 42)·
- `functions/api/watch.js`, `functions/api/errors.js`, το rate limit του sync·
- το `watch.yml`·
- το πρόχειρο της ομάδας (PR 39).

Outputs των εντολών: [`2026-10-14-claude-festive-babbage-gota28-appendix/`](2026-10-14-claude-festive-babbage-gota28-appendix/).

## 1. Verdict

**Κανένα BLOCKING.** Τα tests του developer είναι **σωστά και στοχευμένα**: κάθε bug της 14/10 έχει regression test, και το FakeGame μιμείται πλέον και το 422 «right court position».

Δεν ήταν όμως **αρκετά** σε τρία σημεία:
- η εναλλακτική διαδρομή του `/lineup` όταν το turn plan αλλάζει formation·
- ο κανόνας «έπαιξε = ο αγώνας της ομάδας του σε αυτό το round τελείωσε», για εκτός έδρας ομάδα και για αγώνα άλλου round·
- τα 3 tests για το πρόχειρο που πρότεινε το ίδιο το report του developer (PR 39), που δεν έγιναν ποτέ μόνιμα.

Τα πρόσθεσα όλα.

## 2. Κενά για τον developer (κώδικας προϊόντος)

1. **Ανοιχτό από 08/10: κωδικός sync με ελληνικά γράμματα.** Μέτριο.
   - `web/team.js:146` και `cleanCode` στο `functions/api/sync/[[path]].js`.
   - Τα Α, Β, Ε, Η, Κ, Μ, Ν, Ρ, Τ, Υ, Χ, Ζ πετιούνται και ο κωδικός απορρίπτεται.
   - Fix: αντιστοίχιση στα λατινικά πριν το φιλτράρισμα.
2. **Ανοιχτό από 08/10: `ROLE_LABEL[role] || role` χωρίς `esc()`.** Μέτριο, λανθάνον.
   - `web/team.js:671` και `:686`.
   - Ο server δέχεται ακόμα οποιοδήποτε `roles` στο sync.
   - Fix: `esc(...)` και επικύρωση των `roles` στο `validTeam`.
3. **Το `json()` του sync δεν στέλνει `x-content-type-options: nosniff`** (`functions/api/sync/[[path]].js`, `json`). Χαμηλό. Τα νέα `watch.js`/`errors.js` το στέλνουν. Για συνέπεια, μία γραμμή.
4. **Δύο ορισμοί του «ο αγώνας τελείωσε».** Χαμηλό–μέτριο.
   - Το `elf/checks.py` (`done_teams`) μετράει fixtures **και** `turns[].done`.
   - Το `elf/lineup_cmd.py:62–66` μετράει μόνο fixtures.
   - Αν το `played` των fixtures αργήσει ενώ το turn έχει κλείσει, ο έλεγχος του update θα σε προειδοποιήσει. Ο `/lineup` όμως θα ξαναδώσει τη μπάνταρα σε DNP, το bug της 14/10.
   - Fix: μία κοινή συνάρτηση, π.χ. το `checks.done_teams` να το χρησιμοποιεί και ο `lineup_cmd`.
5. **Το `watch.js` ελέγχει μόνο ότι υπάρχει το header `Cf-Access-Jwt-Assertion`, χωρίς να επικυρώνει το JWT.** Χαμηλό.
   - Σήμερα αρκεί, αφού το Access κάθεται μπροστά σε όλο το `elf-dashboard.pages.dev`: το `/api/*` απαντά 302 χωρίς login (appendix 02 της 08/10).
   - Αν το Access αλλάξει πεδίο εφαρμογής, το header μπορεί να το στείλει ο καθένας. Ο έλεγχος υπογραφής και `aud` θα το έκλεινε.
6. **`errors.js`: ο πίνακας `errors` δεν σβήνεται ποτέ.** Χαμηλό. Τα `hits` καθαρίζονται μόνο όταν υπάρχει κίνηση στο sync. Πρόταση: διαγραφή εγγραφών παλαιότερων των 30 ημερών.

## 3. Tests που προστέθηκαν

| Αρχείο | Test | Τι ελέγχει | Πηγή αναμενόμενων τιμών |
|---|---|---|---|
| `tests/test_lineup_cmd.py` | `test_played_means_this_rounds_game_is_over_home_or_away` | η ομάδα που παίζει εκτός έδρας μετράει ως «έπαιξε», ένας αγώνας άλλου round όχι | κανόνας του παιχνιδιού (σχόλιο 14/10 στον κώδικα) |
| | `test_layout_which_formations_keep_each_played_starter_on_his_slot` | ποια formations κρατούν κάθε βασικό που έπαιξε στη θέση του | λυμένο με το χέρι από τον κανόνα C→F→G του 422 |
| | `test_a_turn_plan_that_would_move_a_played_starter_is_dropped` | η εναλλακτική διαδρομή (γραμμές 158–159): το plan πέφτει, μένει η πεντάδα του optimizer, χωρίς 422 | docstring του `propose` |
| | `test_the_body_has_one_captain_and_never_the_coach` | ακριβώς ένας captain στο body και ποτέ ο coach | κανόνες του παιχνιδιού |
| `tests/test_validate.py` | `test_a_broken_proposal_check_is_a_warning_not_a_stop` | ένα check που σκάει δεν σταματά το update | σχόλιο στο `validate.py` |
| `tests/test_watch.py` | `test_the_workflow_command_saves_only_ids_and_numbers`, `…fails_on_a_broken_list…` | η εντολή του `watch.yml`: δουλεύει **μόνο με τη standard library** (`python -S`), κρατά μόνο ids και αριθμούς, το log δείχνει μόνο πλήθος, και με χαλασμένο JSON αποτυγχάνει χωρίς να γράψει | docstring του `watch.py` |
| `tests/ui/team.spec.mjs` | `the draft never leaves the device…` | κανένα request εκτός GET, κανένα `myteam_v1`/`tm_sync` | κανόνας του owner (13/10) |
| | `the draft goes by itself when the game's team changes…` | το πρόχειρο σβήνει όταν αλλάξει η ομάδα του παιχνιδιού | ίδιος κανόνας |

**Επαλήθευση:**
- Τα νέα tests του `lineup_cmd` πιάνουν 6 από 7 χειροκίνητους mutants (appendix 02).
- Τα UI tests αποτυγχάνουν σε 3 από 3 σκόπιμα σπασίματα του `web/team.js` (appendix 03).
- Ο mutant που ζει (`name_of` με `!=`) είναι equivalent όταν η πεντάδα είναι 2-2-1, γιατί οι εκτός πεντάδας σχηματίζουν επίσης 2-2-1.

## 4. Εύρος tests

- **Python:**
  - 379 passed, coverage 91,97%·
  - diff-cover των PRs 39–44: από 94% σε **96%**.
  - Μένουν ακάλυπτα:
    - δύο αμυντικά `Abort` του `lineup_cmd` (γραμμές 170, 178)·
    - 3 γραμμές του `checks.py`·
    - το `watch.py:132–137`. Το καλύπτει το νέο test μέσω subprocess, αλλά το coverage δεν το μετράει.
- **mutmut (`lineup_cmd`):** 1004/1105 (91%) πριν τα νέα tests. Οι περισσότεροι επιζώντες είναι κείμενα μηνυμάτων και κουμπιών. Οι 16 σημαντικοί του νέου κώδικα αναλύονται στο appendix 02.
- **Τα tests του developer για watch, errors και rate limit** καλύπτουν τα status codes και τα όρια (30/ώρα, 20 alerts/μέρα, 10 νέοι κωδικοί/ώρα).
  - Το docstring του rate-limit test λέει «the IP is kept only as a salted hash», αλλά **δεν το ελέγχει**. Το runner δεν δείχνει τα keys του `hits`.
  - Είναι δουλειά δική μου για το επόμενο run.
- **UI:** δεν έτρεξα όλη τη σουίτα τοπικά, μόνο τα 2 νέα tests σε pc και iphone. Τα PRs 39–44 πέρασαν το UI job στο CI πριν το merge.

## 5. Πίνακας εφαρμοσιμότητας (μόνο όσα αφορά το diff, και τα always-on)

| ID | Status | Αποτέλεσμα |
|----|--------|------------|
| F1 | RUN | 96% στις αλλαγμένες γραμμές |
| F2/F3 | RUN | +formations, +εκτός έδρας/άλλο round, +χαλασμένο JSON |
| F4 | RUN | και τα 2 bugs της 14/10 έχουν regression test (του developer) |
| F5 | RUN | το FakeGame ελέγχει θέσεις και ids |
| F6 | RUN | watch/errors/sync: status codes καλυμμένα |
| F8 | RUN | το rate limit μετράει σωστά ανά IP (test του developer) |
| F12 | RUN | watch χωρίς token → 404, errors χωρίς D1/Telegram → μόνο μέτρηση |
| F14 | RUN | mutmut στο `lineup_cmd`· appendix 02 |
| F15 | RUN | χωρίς flaky |
| S01 | RUN | gitleaks τρέχει πλέον στο CI σε κάθε PR |
| S03 | RUN (review) | watch: μόνο μέσω Access (κενό 5)· sync: ο κωδικός είναι το κλειδί |
| S04 | RUN (review) | κενό 3 |
| S06/S15 | RUN (review) | νέα σημεία που τυπώνουν δεδομένα στη σελίδα (Report, plink, news): escape σωστό· κενό 2 ανοιχτό |
| S07 | RUN | rate limit στο sync και στο errors |
| S10 | RUN | watch: το log δείχνει μόνο πλήθος (test)· errors: χωρίς IP, μόνο salted hash |
| S16 | N/A | το LLM εκτός diff |
| S17 | RUN (review) | errors χωρίς διάρκεια ζωής (κενό 6)· το sync έχει πλέον DELETE |
| S18 | RUN | `watch.yml`: `contents: read`, το input περνά από env και όχι μέσα στο script (σωστό) |

## 6. Παραδοχές και όρια

- Οι αυτόματοι έλεγχοι **δεν αποδεικνύουν ασφάλεια και δεν είναι penetration test**.
- Δεν δοκιμάστηκε τίποτα στο live: το Access, το D1 και το GitHub dispatch εξετάστηκαν μόνο με fakes.
- Τα αρχεία στο `research/` (023, 024) δεν εξετάστηκαν, γιατί δεν είναι κώδικας που τρέχει στο update.
- Εργαλεία: pytest 9.1.1, mutmut 3.8.0 (τοπικά), diff-cover, Playwright από το `tests/ui/package-lock.json`.
