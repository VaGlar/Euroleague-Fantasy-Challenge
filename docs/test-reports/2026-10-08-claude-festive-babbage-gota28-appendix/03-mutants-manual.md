# Χειροκίνητος έλεγχος επιζώντων mutants (mutmut 3.8.0)

Πριν το PR: 1726/2184 πιάστηκαν, 458 επέζησαν. Με τα tests του PR: 2106/2184 πιάστηκαν, 78 επέζησαν.
Εδώ ελέγχονται με το χέρι 10 από τους 78: πρώτα του `validate.py`, μετά το `max_trades`. Για κάθε mutant: τι αλλάζει, αν φαίνεται στη συμπεριφορά, και τι έγινε.

| # | Mutant | Αλλαγή | Ετυμηγορία | Ενέργεια |
|---|--------|--------|------------|----------|
| 1 | `validate.x_check__mutmut_128` | `no_x > 0.1 * len` → `0.1 / len` | **Πραγματικό κενό.** Με ~300 παίκτες το όριο πέφτει στο 0.0003: ένας νέος παίκτης χωρίς xFPT θα σταματούσε όλο το update. | Νέο test `test_a_few_odd_players_do_not_stop_the_update` — πιάνεται |
| 2 | `validate.x_check__mutmut_154` | `0.05 * len(priced)` → `0.05 / len` | **Πραγματικό κενό.** Μία τιμή εκτός 1–40 θα σταματούσε το update. | Ίδιο test — πιάνεται |
| 3 | `validate.x_check__mutmut_188` | `m.get("text") or ""` → `or "XXXX"` | **Πραγματικό κενό.** Μήνυμα report χωρίς `text` περνούσε τον έλεγχο. Το υπάρχον test είχε `"  "`, που είναι truthy. | Νέο test `test_report_message_without_text_stops` — πιάνεται |
| 4 | `validate.x_main__mutmut_2` | `warnings and not problems` → `or` | **Σχεδόν equivalent.** Χωρίς warnings, το `_add_health` ξαναγράφει το `predictions.json` χωρίς περιεχομενική αλλαγή (μόνο ίσως μορφοποίηση). Με problems, το update σταματά ούτως ή άλλως και δεν γίνεται commit. | Κανένα |
| 5 | `validate.x_check__mutmut_61` | `len(players) < 200` → `<= 200` | **Equivalent στην πράξη.** Το όριο είναι αυθαίρετο: το μήνυμα λέει «περίμενα 300+» και τα πραγματικά δεδομένα έχουν 300+. | Κανένα |
| 6 | `validate.x_check__mutmut_104` | `16 <= teams` → `17 <=` | **Equivalent στην πράξη.** Αυθαίρετο όριο: η EuroLeague έχει 18–20 ομάδες, όπως λέει και το μήνυμα. | Κανένα |
| 7 | `validate.x_main__mutmut_41` | `escape(p, quote=False)` → `quote=True` | **Equivalent.** Το Telegram HTML δέχεται `&quot;`. | Κανένα |
| 8 | `validate.x_main__mutmut_15` | `print(..., file=sys.stderr)` → stdout | **Equivalent για τη συμπεριφορά.** Το log του Actions δείχνει και τα δύο. Το exit code δεν αλλάζει. | Κανένα |
| 9 | `optimize.x_transfers__mutmut_1` | default `max_trades=4` → `5` | **Equivalent.** Και οι δύο production callers (`elf/run.py:981`, `elf/autopilot.py:81`) περνούν δικό τους `max_trades`, άρα το default δεν χρησιμοποιείται ποτέ. | Κανένα. Σημείωση: default που δεν χρησιμοποιείται ποτέ |
| 10 | `optimize.x__model__mutmut_7` | όνομα LP `"elf"` → `"ELF"` | **Equivalent.** Το όνομα είναι μόνο ετικέτα του solver. | Κανένα |

Επαλήθευση των 3 νέων tests: κάθε mutant εφαρμόστηκε με το χέρι στο `elf/validate.py`, έτρεξε το `pytest tests/test_validate.py`, και ο κώδικας επανήλθε. Αποτέλεσμα: KILLED ×3. Το `git diff elf/` είναι άδειο.

Πηγή αναμενόμενων τιμών: το docstring του `elf/validate.py`. Τα προβλήματα που σταματούν το update είναι αυτά «that make the data unusable», ενώ οι μικρότερες ανωμαλίες πάνε μόνο στο health. Τα όρια 10% και 5% είναι του κώδικα. Το test ελέγχει μόνο ότι **ένας** μεμονωμένος παίκτης δεν πέφτει πάνω από αυτά.

Οι υπόλοιποι 68 ανήκουν στις κατηγορίες των #5–#10:
- κείμενο μηνυμάτων,
- μορφοποίηση JSON (`indent`, `ensure_ascii`),
- ±1 σε αυθαίρετα όρια,
- stdout ή stderr.
