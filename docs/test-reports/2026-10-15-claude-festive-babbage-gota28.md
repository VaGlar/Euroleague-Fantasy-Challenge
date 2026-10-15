# Αναφορά tester: έλεγχος ασφαλείας (2026-10-15)

**Mode:** analyze + write-tests.

**Εύρος:** όσα σημεία εκτίθενται δεν είχαν ελεγχθεί από άποψη ασφάλειας:
- το Telegram bot (`worker/src/index.js`)·
- το `/feed` (`functions/feed.js`)·
- οι εξαρτήσεις·
- πώς τα workflows χρησιμοποιούν τα inputs τους.

Μόνο ανάγνωση κώδικα και tests σε node. Χωρίς επίθεση στο live. Στο live έγιναν μόνο δύο αιτήματα στο `/feed` του δημόσιου site, που δεν προωθούν τίποτα («bad url», «host not allowed»).

## 1. Verdict

**Κανένα BLOCKING κατά τους κανόνες** (δεν αναπαράχθηκε στο live).

Ένα **σημαντικό κενό, μέτριο–υψηλό, στο `/feed`**: είναι ανοιχτό στο δημόσιο site και μπορεί να γίνει όχημα για XSS στο domain σου. Κατά τα άλλα, το bot και τα workflows είναι σωστά προστατευμένα.

## 2. Κενά για τον developer

1. **`functions/feed.js` (μέτριο–υψηλό).** Το επιβεβαίωσα στο `hoopslab-beta.pages.dev/feed`: είναι deployed και στο δημόσιο site, χωρίς Cloudflare Access.
   - **(α) Redirects:** το `fetch` των Workers ακολουθεί redirects, και η allowlist ελέγχει μόνο τον host που ζητήθηκε. Ένα Substack με custom domain κάνει redirect εκεί, εκτός λίστας.
   - **(β) Content-type:** η απάντηση βγαίνει με το content-type της πηγής (`text/html`) από το origin του site, χωρίς CSP, αφού το `_headers` δεν φτάνει στις Functions.
   - **Σενάριο:** ένα link `…/feed?u=https://<x>.substack.com/…` ανοίγει σελίδα του επιτιθέμενου στο domain σου. Το JavaScript της διαβάζει ή αλλάζει το localStorage: τον κωδικό sync και την ομάδα.
   - **Fix:**
     - μετά το `fetch`, ξαναέλεγχος του `new URL(r.url).hostname` με την ίδια allowlist·
     - απάντηση πάντα `text/plain` με `x-content-type-options: nosniff` και `content-security-policy: sandbox`, αφού το pipeline διαβάζει μόνο κείμενο·
     - προαιρετικά, το `/feed` να απαντά μόνο στο προσωπικό site (με Access), αφού μόνο το pipeline το χρειάζεται.
   - **Tests:** `tests/test_feed_fn.py`, 2 strict xfail. Με το fix γίνονται XPASS: αφαίρεσε το `@FEED_GAP` στο ίδιο commit. Το επαλήθευσα με το fix εφαρμοσμένο με το χέρι: περνούν και τα 55 tests του `/feed` και του `news.py`.
2. **`npx --yes wrangler@4` σε 11 σημεία των workflows (χαμηλό–μέτριο, supply chain).**
   - Κάθε deploy κατεβάζει την τελευταία 4.x και την τρέχει με το `CLOUDFLARE_API_TOKEN`. Μια κακόβουλη έκδοση του wrangler θα είχε το token.
   - **Fix:** συγκεκριμένη έκδοση (`wrangler@4.x.y`), ενημέρωση με το χέρι ή με Dependabot.
   - Αφορά shared workflows, άρα χρειάζεται έγκριση του owner.

## 3. Τι είναι σωστό

- **Bot, webhook:** χωρίς το σωστό `X-Telegram-Bot-Api-Secret-Token` απαντά 403, και 403 όταν λείπει το secret.
- **Bot, owner:** όλες οι εντολές και τα κουμπιά ελέγχουν το chat ID του owner. Το `/start` απαντά σε όλους μόνο με το δικό τους chat ID.
- **Bot, κουμπί «✅ Εφάρμοσε»:**
  - το nonce περνά από regex `^[a-f0-9]{12}$`·
  - τα κουμπιά αφαιρούνται μετά το πρώτο πάτημα·
  - διπλό πάτημα ή παλιό κουμπί δεν κάνει ζημιά, γιατί το `lineup_cmd.apply` ξαναϋπολογίζει την πρόταση και απορρίπτει nonce που δεν ταιριάζει (test από 08/10).
- **Workflows:**
  - όλα τα inputs (`mode`, `nonce`, `watch`) περνούν από `env:`, όχι μέσα στο script, άρα δεν υπάρχει script injection·
  - δεν υπάρχει `pull_request_target`·
  - τα PRs από forks τρέχουν χωρίς secrets.
- **Εξαρτήσεις:**
  - `pip-audit`: καθαρό·
  - `npm audit` στο `tests/ui`: 0 vulnerabilities·
  - ο worker δεν έχει εξαρτήσεις.

## 4. Για τον owner

- **Δικαιώματα των tokens:** έλεγξε ότι το `GH_DISPATCH_TOKEN` είναι fine-grained με μόνο «Actions: read/write» σε αυτό το repo, όπως γράφει ο κώδικας. Τα `DATA_REPO_TOKEN` και `CLOUDFLARE_API_TOKEN` να έχουν μόνο ό,τι χρειάζονται.
- **GitHub:** secret scanning, Dependabot alerts και 2FA στον λογαριασμό. Δεν τα βλέπω από εδώ.

## 5. Tests που προστέθηκαν

| Αρχείο | Test | Πηγή αναμενόμενων τιμών |
|---|---|---|
| `tests/test_feed_fn.py` + `feed_fn_runner.mjs` | `test_only_https_on_the_allowed_hosts` (περνά) | το σχόλιο του `feed.js` («allow-listed hosts only, so it can't be used as an open proxy») |
| | `test_a_redirect_off_the_list_is_refused` (strict xfail) | ίδιο σχόλιο: η allowlist να ισχύει και μετά από redirect |
| | `test_the_answer_is_never_a_page_of_our_site` (strict xfail) | κανόνας ασφαλείας: περιεχόμενο τρίτων όχι ως σελίδα του origin |

`CLAUDE.md`: προστέθηκε ο κανόνας του owner «UI tests (Playwright) only in CI, never in a Claude session».

## 6. Όρια

- Δεν είναι penetration test.
- Το redirect μέσω Substack custom domain δεν αναπαράχθηκε στο live. Η απόδειξη βασίζεται στον κώδικα, στη default συμπεριφορά του `fetch` (`redirect: "follow"`) και στο test σε node.
- Τα δικαιώματα των tokens και οι ρυθμίσεις του GitHub δεν είναι ορατά από εδώ.
