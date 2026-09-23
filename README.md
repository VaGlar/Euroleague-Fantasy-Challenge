# EuroLeague Fantasy Challenge — helper

Προσωπικό εργαλείο για το [EuroLeague Fantasy Challenge](https://euroleaguefantasy.euroleaguebasketball.net/10):
κατάταξη παικτών με βάση δεδομένα, νέα και γνώμες ειδικών, προτάσεις για αλλαγές και αρχηγό,
ειδοποίηση στο Telegram στις 11:00 κάθε μέρας αγώνων. Κόστος: 0 €.

## Αρχιτεκτονική

| Κομμάτι | Πού τρέχει | Τι κάνει |
|---|---|---|
| `elf/` (Python) | GitHub Actions (3×/μέρα) | στατιστικά EuroLeague, τιμές fantasy, νέα, xPIR, report |
| `web/` | Cloudflare Pages | dashboard (PWA: «Προσθήκη στην αρχική οθόνη» στο iPhone) |
| `worker/` | Cloudflare Workers | ειδοποίηση 11:00 Αθήνας + εντολές bot (`/report`, `/top`, `/health`) |
| `sources.yaml` | — | λίστα πηγών νέων (πρόσθεσε RSS feeds εδώ) |

## Μοντέλο

```
xPIR = base × (1 + calib + pos·pos_dev + pace·pace_dev + margin·m/10 + blowout·|m|/10 + home·h)
```
- **base**: blend PIR τελευταίων 3 / σεζόν / περσινής (DNP μετράει 0).
- **Team rating**: net rating ανά 100 κατοχές + pace + πλεονέκτημα έδρας *ανά ομάδα* (shrinkage).
- **pos_dev**: PIR που δίνει ο αντίπαλος στη θέση του παίκτη vs μέσος όρος.
- **m**: αναμενόμενη διαφορά σκορ (ratings + έδρα) → blowouts κόβουν λεπτά.
- **availability**: από τα νέα (Gemini) — out ×0, doubtful ×0.4, questionable ×0.8.
- Τα βάρη **δεν είναι με το μάτι**: `python -m elf.backtest 2025 --save` τα ρυθμίζει με walk-forward backtest.

## Setup (μία φορά)

1. **GitHub Secrets** (Settings → Secrets and variables → Actions):
   `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
   `FANTASY_TOKEN`, και αργότερα `TELEGRAM_CHAT_ID`.
2. Merge στο `main` (τα scheduled workflows τρέχουν μόνο από το default branch).
3. Actions → **Deploy Telegram bot** → Run workflow.
4. Στείλε `/start` στο bot → σου απαντά το chat ID → βάλ' το στο secret `TELEGRAM_CHAT_ID`
   → ξανατρέξε το **Deploy Telegram bot**.
5. Actions → **Update data & dashboard** → Run workflow (το πρώτο τρέχει και το backtest).
6. Άνοιξε `https://elf-dashboard.pages.dev` στο Safari → Share → Add to Home Screen.

### Fantasy token
Από υπολογιστή: login στο site → F12 → Network → φίλτρο `dunkest` → refresh →
κλικ σε request προς `fantaking-api.dunkest.com` → Request Headers → `Authorization: Bearer …` →
αντέγραψε ό,τι ακολουθεί το `Bearer ` στο secret `FANTASY_TOKEN`.
- Αν είναι JWT, το pipeline διαβάζει την ημερομηνία λήξης και σε προειδοποιεί **3 μέρες πριν**.
- Αν είναι opaque token, η λήξη φαίνεται μόνο από `401`. Τότε το report και το `/health` το αναφέρουν.
- **Fallback χωρίς token:** αντέγραψε το `my_team.example.yaml` σε `my_team.yaml` με τους 10 παίκτες σου.
  Πρόταση αρχηγού και xPIR της ομάδας δουλεύουν κανονικά. Τιμές και προτάσεις αλλαγών χρειάζονται το token.
- Χρήση: μόνο GET, 3 φορές τη μέρα, για τον δικό σου λογαριασμό. Είναι ανεπίσημο API και μπορεί να αλλάξει χωρίς προειδοποίηση.

### Telegram `/update` (προαιρετικό)
Ξεκινάει το update από το κινητό και σου γράφει όταν τελειώσει.
1. GitHub → Settings (του λογαριασμού) → Developer settings → Personal access tokens →
   **Fine-grained tokens** → Generate new token.
2. Repository access: **Only select repositories** → αυτό το repo.
3. Permissions → Repository permissions → **Actions: Read and write**. Τίποτα άλλο.
4. Expiration: έως το τέλος της σεζόν.
5. Βάλ' το στο secret `GH_DISPATCH_TOKEN` και ξανατρέξε το **Deploy Telegram bot**.

### Telegram `/lineup`
Προτείνει πεντάδα, 6ο και αρχηγό από την **πραγματική** σου ομάδα και, αν πατήσεις ✅, τα εφαρμόζει στο παιχνίδι.
- Γράφει **μόνο** πεντάδα/πάγκο/αρχηγό, **ποτέ** μεταγραφές.
- Πεντάδα και 6ος μόνο από παίκτες του τρέχοντος Turn· όσοι παίζουν σε επόμενο Turn μένουν στον πάγκο με πλάνο αλλαγής («αν ο X φέρει κάτω από N, βάλε τον Y»). Εξαίρεση μόνο αν δεν βγαίνει έγκυρη πεντάδα (π.χ. κανένας C στο T1).
- Σέβεται τους κανόνες μέσα στην αγωνιστική: παίκτης που έπαιξε από τον πάγκο μένει στον πάγκο, αρχηγός γίνεται μόνο όποιος δεν έχει παίξει.
- Πριν γράψει ελέγχει ότι διαβάζει σωστά την ομάδα (formation, σειρά θέσεων). Αν κάτι δεν ταιριάζει ή η πρόταση άλλαξε από τη στιγμή που την είδες, **σταματά χωρίς αλλαγές**.
- Μετά την αποθήκευση ξαναδιαβάζει την ομάδα και επιβεβαιώνει κάθε θέση.
- Χρειάζεται το `GH_DISPATCH_TOKEN` (ίδιο με το `/update`).

### Στήλες fantasy (ειδικοί)
Στο `sources.yaml` οι πηγές με `fantasy: true` (επίσημα Fantasy Tips, Basketball Sphere, EuroBallin)
διαβάζονται ολόκληρες. Το Gemini καταγράφει ποιον προτείνει κάθε στήλη (pick / captain / avoid).
- Επίδραση στο xPTS **μόνο της τρέχουσας αγωνιστικής**, σκόπιμα μικρή: +5% ανά στήλη (έως 2), +3% αν προτείνεται αρχηγός, −8% αν «avoid», όριο −15%/+13%.
- Κάθε πρόταση γράφεται στο `data/public/expert_log.csv` μαζί με το xPTS του μοντέλου **πριν** την επίδραση — μετά από μερικές αγωνιστικές μετράμε αν οι στήλες προβλέπουν καλύτερα και ρυθμίζουμε τα ποσοστά.
- Παίκτες χωρίς ιστορικό EuroLeague παίρνουν εκτίμηση από την τιμή τους (−20% για την αβεβαιότητα).

### $ — πρόβλεψη ανόδου τιμής
- Μέχρι να υπάρξουν 2 αγωνιστικές τιμών: $ όταν το xPTS ξεπερνά αυτό που «αντιστοιχεί» στην τιμή κατά 3+ πόντους **και** 30%+ (οι φτηνοί ανεβαίνουν πιο εύκολα).
- Μετά: το σύστημα μαθαίνει αυτόματα από το `prices.csv` πώς αλλάζει η τιμή με βάση πόντους και τιμή, και $ σημαίνει προβλεπόμενη άνοδο ≥ +0.3cr (↓$ πτώση).

### Προτιμήσεις (`preferences.yaml`)
`keep`: παίκτες που δεν θέλεις να σου προτείνει να πουλήσεις (π.χ. έχεις άποψη που το μοντέλο δεν ξέρει).
`avoid`: παίκτες που δεν θέλεις να σου προτείνει. Αλλάζεις το αρχείο από το GitHub (✏️) και τρέχεις `/update`.

## Τοπικά
```
pip install -r requirements.txt
python -m elf.history 2025 2026     # κατέβασμα ιστορικού
python -m elf.backtest 2025 --save  # ρύθμιση βαρών
python -m elf.run                   # πλήρες pipeline
python -m elf.fantasy dump          # debug: τι επιστρέφει το fantasy API (θέλει FANTASY_TOKEN)
```
