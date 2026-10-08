# Αναφορά tester: claude/vibrant-cannon-u7rds6 έναντι main (2026-10-08)

Mode: **analyze**. Εύρος: το diff `origin/main...HEAD`, που αφορά μόνο τα `web/team.js` και `tests/ui/team.spec.mjs`. Είναι το πρόχειρο (draft) της ομάδας στην προσωπική έκδοση.

## 1. Verdict

**Κανένα BLOCKING.** Το σημαντικότερο κενό: δεν υπάρχει μόνιμο test ότι το πρόχειρο **σβήνει μόνο του όταν αλλάξει η ομάδα του παιχνιδιού**. Η συμπεριφορά δουλεύει, αφού την επιβεβαίωσε probe, αλλά κανένα test δεν την κλειδώνει.

## 2. Κενά (κατά προτεραιότητα)

1. **Μεσαίο: το πρόχειρο σβήνει όταν αλλάξει η ομάδα ή το trade round (`myTeam`, `gameSig`).**
   - Είναι ο βασικός μηχανισμός ασφαλείας: ένα παλιό πρόχειρο δεν πρέπει να κρύβει την πραγματική ομάδα. Αν χαλάσει, ο χρήστης βλέπει πρόχειρο αντί για την πραγματική ομάδα του παιχνιδιού.
   - Έλεγχος με probe: η αλλαγή του `sig` στο storage και reload φέρνουν πίσω την ομάδα του παιχνιδιού, και το κλειδί σβήνεται. **Πέρασε.**
   - Πρόταση: μόνιμο UI test με αυτά τα βήματα, ή ένα fixture με διαφορετικό `trade_round`.
2. **Μεσαίο: το ✓ σε προτεινόμενο trade (`data-i` / `data-n`) στην προσωπική έκδοση.**
   - Τα tests του developer καλύπτουν Trade από την κάρτα και ✕, όχι το ✓. Το ✓ είναι το σημείο όπου περνάμε από τις προτάσεις του server στον υπολογισμό στον browser (`tradesFor` με `t.draft`).
   - Έλεγχος με probe: ✓ → «Πρόχειρο», το ίδιο trade δεν ξαναπροτείνεται. **Πέρασε.**
   - Πρόταση: μόνιμο test.
3. **Μεσαίο (ιδιωτικότητα): το πρόχειρο δεν βγαίνει από τη συσκευή.**
   - Η προσωπική ομάδα δεν πρέπει να φτάνει στο sync API (D1) ή στο `myteam_v1` της public έκδοσης.
   - Έλεγχος με probe: κανένα non-GET request, ούτε `tm_sync` ούτε `myteam_v1` στο storage. **Πέρασε.**
   - Ανασκόπηση: το `save()` επιστρέφει πριν από το `syncLater()` όταν `t.game`.
   - Πρόταση: μόνιμο test, γιατί είναι ο κανόνας «τίποτα προσωπικό έξω».
4. **Χαμηλό: χαλασμένο `tm_draft` στο storage** (μη έγκυρο JSON ή χωρίς `team`).
   - Έλεγχος με probe: η σελίδα δείχνει 11 παίκτες χωρίς JS errors. **Πέρασε.**
5. **Χαμηλό, ανασκόπηση και όχι test: trades στο πρόχειρο ενώ τρέχει το round.**
   - Το `nextTrades` έχει πια ✓ και στην προσωπική έκδοση. Ένα trade για το επόμενο round μετράει στο `t.used` του `trade_round`, που είναι σωστό.
   - Κανένα test δεν καλύπτει πρόχειρο κατά τη διάρκεια round. Χρειάζεται fixture με round σε εξέλιξη για την προσωπική έκδοση.
6. **Χαμηλό, σχεδιαστικό: μη ντετερμινιστικό σβήσιμο.**
   - Το πρόχειρο κρατά το `gain` του server και το `sig` περιέχει το `bank` του παιχνιδιού.
   - Αν το παιχνίδι αλλάξει το `bank` χωρίς trade, π.χ. από διόρθωση τιμής, το πρόχειρο σβήνει. Αυτό είναι αποδεκτό.

## 3. Tests που προστέθηκαν

Κανένα μόνιμο, αφού το mode είναι analyze. Τα probes των κενών 1 έως 4 γράφτηκαν προσωρινά στο `tests/ui/_probe.spec.mjs`, έτρεξαν σε pc και iphone (6/6 passed) και σβήστηκαν.

Αν το εγκρίνεις, σε write-tests mode τα κάνω μόνιμα tests στο `tests/ui/team.spec.mjs`. Οι αναμενόμενες τιμές προέρχονται από την προδιαγραφή του owner στη συζήτηση: το πρόχειρο μένει μόνο στη συσκευή και σβήνει όταν αλλάξει η ομάδα στο παιχνίδι.

## 4. Εύρος των tests (F1–F15) για την αλλαγή

| | Κατάσταση |
|---|---|
| F1 νέα συμπεριφορά | Καλύπτεται: trade → πρόχειρο, reload, ακύρωση, ✕, trades left. Λείπει: ✓ σε πρόταση, σβήσιμο όταν αλλάξει η ομάδα |
| F2 όρια | Μερικώς: trades left = 1 → 4/4. Λείπει: 0 trades left με ✕ (μήνυμα «Δεν σου μένουν Trades») |
| F3 σφάλματα | Λείπει μόνιμο test για χαλασμένο storage (το probe πέρασε) |
| F4 regression | Δεν ισχύει (feature, όχι bugfix) |
| F10 e2e | Καλύπτεται από Playwright σε 4 συσκευές |
| F14 ποιότητα | Τα νέα tests έχουν ουσιαστικούς ελέγχους (ids στο γήπεδο, κεφαλίδα, reload) |
| F15 flaky | Καμία αποτυχία σε 64+6 εκτελέσεις |
| F5–F9, F11–F13 | Εκτός εύρους της αλλαγής (μόνο UI στον browser) |

## 5. Πίνακας εφαρμογής

| ID | Κατάσταση | Αιτία / στοιχεία | Αποτέλεσμα |
|---|---|---|---|
| F1 | RUN | diff στο `web/team.js` | 63 passed, 1 skipped (υπήρχε ήδη) · κενά 1–2 |
| F2 | RUN | trades left | βλ. §4 |
| F3 | RUN | localStorage input | probe passed |
| F4 | N/A | δεν είναι bugfix (commit 9974417: feature) | – |
| F5 | N/A | το diff δεν αγγίζει DB ή εξωτερικές υπηρεσίες | – |
| F6 | N/A | το diff δεν αγγίζει `functions/api` | – |
| F7 | N/A | αριθμητική credits: ίδιο `applyTrade` με την public, καλύπτεται ήδη | – |
| F8 | N/A | καμία νέα ταυτόχρονη ή επαναλαμβανόμενη ροή | – |
| F9 | N/A | καμία νέα pure function | – |
| F10 | RUN | `WEB_UI` | passed (pc, android-small· probes και σε iphone) |
| F11 | N/A | καμία migration στο diff | – |
| F12 | N/A | καμία νέα ρύθμιση ή μεταβλητή | – |
| F13 | N/A | καμία επεξεργασία μεγάλου όγκου | – |
| F14 | RUN | ανασκόπηση νέων tests | ΟΚ |
| F15 | RUN | επανάληψη | καμία αστάθεια |
| S01 | RUN | grep στο diff (gitleaks/trufflehog δεν είναι εγκατεστημένα) | καθαρό: μόνο το όνομα `FANTASY_TOKEN` σε υπάρχον μήνυμα, χωρίς τιμή |
| S02 | N/A | καμία αλλαγή εξαρτήσεων στο diff | – |
| S03 | N/A | καμία αλλαγή ελέγχου πρόσβασης· το πρόχειρο είναι τοπικό | – |
| S04 | N/A | καμία αλλαγή config ή headers | – |
| S05 | N/A | καμία κρυπτογραφία | – |
| S06 | RUN | rendering στο `WEB_UI` | ανασκόπηση: τα ονόματα περνούν από `esc()`· τα ids από το storage φιλτράρονται από το `row()` (αυστηρή σύγκριση) |
| S07 | N/A | κανένα νέο endpoint | – |
| S08 | N/A | `AUTH` false (δεν υπάρχει login) | – |
| S09 | RUN | `JSON.parse` δεδομένων από το storage | ασφαλές (χωρίς eval)· η αποτυχία πιάνεται σε try/catch |
| S10 | RUN | `PERSONAL_DATA` | κανένα log· τα νέα tests δεν τυπώνουν προσωπικά δεδομένα (fixtures μόνο) |
| S11 | RUN | χαλασμένο storage | fail-safe, probe passed |
| S12 | N/A | κανένα upload ή αρχείο | – |
| S13 | N/A | κανένα API στο diff | – |
| S14 | N/A | καμία ανάκτηση URL | – |
| S15 | RUN | client-side | καμία καινούργια διαδρομή postMessage ή innerHTML με είσοδο χρήστη |
| S16 | N/A | το diff δεν αγγίζει LLM (`elf/news.py`) | – |
| S17 | RUN | `PERSONAL_DATA` | το πρόχειρο μένει στη συσκευή και δεν στέλνεται (probe)· διατήρηση: σβήνει με την αλλαγή του round. Δεν είναι νομικό συμπέρασμα |
| S18 | N/A | το diff δεν αγγίζει workflows | – |

## 6. Προφίλ project

- **Τεχνολογίες:**
  - Python 3.11 για το pipeline (`elf/`, `requirements.txt`) με pytest (`pytest.ini`).
  - Vanilla JS dashboard (`web/`) με Playwright 1.56.1 (`tests/ui/package.json`).
  - Cloudflare Pages Functions με D1 (`functions/api/sync`).
  - Cloudflare Worker για το Telegram (`worker/`).
- **Flags:**
  - `WEB_UI` ✓ (`web/`)
  - `HTTP_API` ✓ (`functions/api/sync`)
  - `DB_SQL` ✓ (D1, binding `SYNC_DB`)
  - `SECRETS_USED` ✓ (secrets στα workflows)
  - `PERSONAL_DATA` ✓ (η ομάδα του owner, `elf/publish.py` PRIVATE_ONLY)
  - `LLM_FEATURES` ✓ (`elf/news.py`, Gemini)
  - `CI` ✓ (`.github/workflows`)
  - `DEPLOYED_PUBLIC` ✓ (Cloudflare Pages, public repo)
  - `DATA_PIPELINE` ✓, `CALCULATIONS` ✓ (credits, xFPT)
  - `DEPENDENCIES` ✓
  - `AUTH` ✗ (κανένα login· το sync δουλεύει με κωδικό)
  - `FILE_UPLOAD` ✗, `PAYMENTS` ✗, `BROWSER_EXTENSION` ✗
  - `EXTERNAL_HTTP`: UNKNOWN (πηγές από το `sources.yaml`, όχι από τον χρήστη)
  - `DB_MIGRATIONS`: UNKNOWN
- **Τεκμηρίωση:** δεν υπάρχουν `TESTING.md` ή `SPEC.md`, οπότε δεν υπάρχει όριο για mutation score. Δεν βρέθηκε ούτε `CODEOWNERS` για τα `.github/workflows/`.

## 7. Παραδοχές και όρια

- Οι αυτόματοι και στατικοί έλεγχοι **δεν αποδεικνύουν ασφάλεια** και δεν είναι penetration test.
- Δεν έτρεξαν:
  - τα UI tests στα projects `iphone` και `android` για όλο το `team.spec.mjs` (μόνο pc και android-small)·
  - τα pytest, επειδή δεν υπάρχει αλλαγή Python στο diff·
  - gitleaks, trufflehog και mutation testing, επειδή τα εργαλεία δεν είναι εγκατεστημένα.
- Ο πλήρης κατάλογος μένει για το nightly run.
- Εκδόσεις: Playwright 1.56.1, Chromium από το `/opt/pw-browsers`. Ο κατάλογος γράφτηκε για OWASP Top 10:2025, ASVS 5.0.0, WSTG 4.2. Δεν έλεγξα online για νεότερες εκδόσεις.
