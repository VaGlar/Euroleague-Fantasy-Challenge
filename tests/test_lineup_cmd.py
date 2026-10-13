"""/lineup end to end against a fake game: propose -> apply -> read back."""
import json

import pytest

from elf import lineup_cmd

from conftest import FakeGame, squad_t1_t2, write_predictions

# a turn-blind lineup: turn-2 players in the five, turn-1 players on the bench
BAD = {10: "5άδα", 5: "5άδα", 8: "5άδα", 1: "5άδα", 3: "5άδα", 2: "6ος",
       6: "πάγκος", 7: "πάγκος", 9: "πάγκος", 4: "πάγκος"}
GOOD = {1: "5άδα", 2: "5άδα", 5: "5άδα", 6: "5άδα", 9: "5άδα", 7: "6ος",
        3: "πάγκος", 4: "πάγκος", 8: "πάγκος", 10: "πάγκος"}


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(lineup_cmd, "say", lambda *a, **k: None)


def game(monkeypatch, public, roles, captain, **kw):
    sq = squad_t1_t2()
    write_predictions(public, sq)
    return FakeGame(sq, roles, captain, **kw).install(monkeypatch)


def test_preview_then_apply_turn1(monkeypatch, public):
    g = game(monkeypatch, public, BAD, captain=10)
    st = lineup_cmd.load_state()
    assert st["direction"] == -1                     # the game orders the five C -> F -> G
    pr = lineup_cmd.propose(st)
    assert pr["changes"]
    lineup_cmd.apply(pr["nonce"])
    roles, cap = g.lineup()
    assert roles == GOOD and cap == 1
    # the saved body is a legal lineup for the game
    assert pr["body"]["formation_id"] == 27          # 2-2-1
    assert len(g.saved) == 1
    # running again finds nothing to change
    assert lineup_cmd.propose(lineup_cmd.load_state())["changes"] == []


def test_nothing_to_change_does_not_write(monkeypatch, public):
    g = game(monkeypatch, public, GOOD, captain=1)
    pr = lineup_cmd.propose(lineup_cmd.load_state())
    assert pr["changes"] == []
    lineup_cmd.apply(pr["nonce"])
    assert g.saved == []


def test_stale_confirmation_is_refused(monkeypatch, public):
    g = game(monkeypatch, public, BAD, captain=10)
    with pytest.raises(lineup_cmd.Abort, match="άλλαξε"):
        lineup_cmd.apply("000000000000")
    assert g.saved == []


T1_PTS = {1: 30, 2: 2, 5: 25, 6: 3, 7: 1, 9: 0}


def test_turn2_morning_legal_swaps_are_applied(monkeypatch, public):
    g = game(monkeypatch, public, GOOD, captain=1, played=T1_PTS)
    before = {p["id"]: p["court_position"] for p in g.state["players"]}
    pr = lineup_cmd.propose(lineup_cmd.load_state())
    lineup_cmd.apply(pr["nonce"])                   # the fake game answers 422 on illegal moves
    roles, cap = g.lineup()
    assert {i for i, r in roles.items() if r == "5άδα"} == {1, 5, 3, 8, 10}
    assert roles[2] == roles[6] == roles[9] == "πάγκος" and cap == 1
    after = {p["id"]: p["court_position"] for p in g.state["players"]}
    assert after[1] == before[1] and after[5] == before[5], "όσοι μένουν κρατούν τη θέση τους"


def test_mantzoukas_case_sixth_man_who_played_is_not_moved_into_the_five(monkeypatch, public):
    # 22/9 bug: a played sixth man was moved into the five -> 422
    pts = {1: 1, 2: 2, 5: 3, 6: 3, 9: 3, 7: 40}
    g = game(monkeypatch, public, GOOD, captain=1, played=pts)
    pr = lineup_cmd.propose(lineup_cmd.load_state())
    lineup_cmd.apply(pr["nonce"])
    roles, _ = g.lineup()
    assert roles[7] in ("6ος", "πάγκος")


def test_illegal_move_is_reported(monkeypatch, public):
    g = game(monkeypatch, public, GOOD, captain=1, played=T1_PTS)
    st = lineup_cmd.load_state()
    pr = lineup_cmd.propose(st)
    body = pr["body"]
    six = next(b for b in body["players"] if b["id"] == 7)
    one = next(b for b in body["players"] if b["id"] == 1)
    six["court_position"], one["court_position"] = one["court_position"], six["court_position"]
    assert g.save_roster(g.TEAM, g.MATCHDAY, body).status_code == 422


def test_wrong_formation_id_aborts(monkeypatch, public):
    g = game(monkeypatch, public, BAD, captain=10)
    g.state["formation_id"] = 31                     # says 3-1-1, the five is 2-2-1
    with pytest.raises(lineup_cmd.Abort, match="formation"):
        lineup_cmd.load_state()


def test_unknown_slot_order_aborts(monkeypatch, public):
    g = game(monkeypatch, public, BAD, captain=10)
    five = sorted(g.state["players"], key=lambda p: p["court_position"])[:5]
    five[0]["court_position"], five[2]["court_position"] = \
        five[2]["court_position"], five[0]["court_position"]   # C F F G G -> F F C G G
    with pytest.raises(lineup_cmd.Abort, match="διάταξη"):
        lineup_cmd.load_state()


def test_game_rejects_save(monkeypatch, public):
    game(monkeypatch, public, BAD, captain=10, status=500)
    pr = lineup_cmd.propose(lineup_cmd.load_state())
    with pytest.raises(lineup_cmd.Abort, match="απέρριψε"):
        lineup_cmd.apply(pr["nonce"])


def test_save_not_persisted_is_detected(monkeypatch, public):
    game(monkeypatch, public, BAD, captain=10, persist=False)
    pr = lineup_cmd.propose(lineup_cmd.load_state())
    with pytest.raises(lineup_cmd.Abort, match="δεν έχουν τη θέση"):
        lineup_cmd.apply(pr["nonce"])


def test_incomplete_roster_aborts(monkeypatch, public):
    g = game(monkeypatch, public, BAD, captain=10)
    g.state["players"].pop()
    with pytest.raises(lineup_cmd.Abort, match="11"):
        lineup_cmd.load_state()


def test_locked_league_gives_clear_message(monkeypatch, public):
    reply = '{"code": "FORBIDDEN", "message": "The league status does not allow the request."}'
    g = game(monkeypatch, public, BAD, captain=10, status=403, league_status=2, reply=reply)
    said = []
    monkeypatch.setattr(lineup_cmd, "say", lambda text, *a, **k: said.append(text))
    lineup_cmd.preview()
    assert "🔒" in said[-1], "η προεπισκόπηση πρέπει να προειδοποιεί ότι είναι κλειδωμένο"
    pr = lineup_cmd.propose(lineup_cmd.load_state())
    with pytest.raises(lineup_cmd.Abort, match="🔒"):
        lineup_cmd.apply(pr["nonce"])
    assert g.lineup()[1] == 10, "τίποτα δεν άλλαξε"


def test_game_error_page_reaches_telegram_escaped(monkeypatch, public):
    """The game (or a proxy in front of it) may answer with an HTML error page: quoted raw,
    Telegram would reject the ⛔ message and the user would never hear the apply failed."""
    game(monkeypatch, public, BAD, captain=10, status=502,
         reply="<html><body>502 Bad Gateway</body></html>")
    said = []
    monkeypatch.setattr(lineup_cmd, "say", lambda text, buttons=None: said.append(text))
    pr = lineup_cmd.propose(lineup_cmd.load_state())
    assert lineup_cmd.main(["apply", pr["nonce"]]) == 0
    (text,) = said
    assert text.startswith("⛔ /lineup:") and "<html>" not in text
    assert "&lt;html&gt;" in text and "502" in text


def test_main_token_error_exits_nonzero(monkeypatch):
    said = []
    monkeypatch.setattr(lineup_cmd, "say", lambda text, buttons=None: said.append(text))

    def no_token():
        raise lineup_cmd.fantasy.TokenError("FANTASY_TOKEN is not set")
    monkeypatch.setattr(lineup_cmd, "load_state", no_token)
    assert lineup_cmd.main(["preview", ""]) == 1 and "FANTASY_TOKEN" in said[0]


def test_apply_confirmation_shows_the_lineup_without_the_list_of_subs(monkeypatch, public):
    """The preview lists the subs; the ✅ after apply shows only the resulting lineup. describe()'s
    text is cut at the subs heading, so renaming that heading in one place only would break it."""
    g = game(monkeypatch, public, BAD, captain=10)
    said = []
    monkeypatch.setattr(lineup_cmd, "say", lambda text, buttons=None: said.append(text))
    st = lineup_cmd.load_state()
    pr = lineup_cmd.propose(st)
    preview = lineup_cmd.describe(st, pr)
    heading = "\n\n" + preview.split("\n\n")[-1].split("\n")[0]       # the subs heading, whatever its name
    assert "→" in preview.split(heading)[-1], "η πρόταση δείχνει τις αλλαγές"
    lineup_cmd.apply(pr["nonce"])
    (done,) = said
    assert done.startswith("✅") and heading.strip() not in done and "→" not in done
    assert g.lineup()[0] == GOOD


# ------------------------------------------------------------------ found by mutation testing

def buttons_of(said):
    return [b for _, b in said]


def test_preview_sends_the_proposal_with_apply_and_cancel_buttons(monkeypatch, public):
    game(monkeypatch, public, BAD, captain=10)
    said = []
    monkeypatch.setattr(lineup_cmd, "say", lambda text, buttons=None: said.append((text, buttons)))
    assert lineup_cmd.main([]) == 0                  # no argument = preview (the bot's /lineup)
    (text, buttons), = said
    nonce = lineup_cmd.propose(lineup_cmd.load_state())["nonce"]
    assert buttons == [{"text": "✅ Εφάρμοσε", "callback_data": f"lu:apply:{nonce}"},
                       {"text": "❌ Άκυρο", "callback_data": "lu:cancel"}], "το bot διαβάζει αυτά τα callback_data"
    assert text.endswith("Να εφαρμοστεί στο παιχνίδι;") and "🔒" not in text
    subs = text.split("<b>Subs:</b>\n")[1].split("\n\n")[0].splitlines()
    assert "• P10: 5άδα → πάγκος" in subs and "• P7: πάγκος → 6ος" in subs and "• ★ Captain: P1" in subs
    assert len(subs) == 8, "μία γραμμή ανά αλλαγή ρόλου + η μπάνταρα, όχι όσοι μένουν ίδιοι"
    assert "P1 (G)" in text and "6ος: P7 (F)" in text and "Πριν το T2" in text


def test_preview_with_nothing_to_change_has_no_buttons_even_when_locked(monkeypatch, public):
    game(monkeypatch, public, GOOD, captain=1, league_status=2)
    said = []
    monkeypatch.setattr(lineup_cmd, "say", lambda text, buttons=None: said.append((text, buttons)))
    lineup_cmd.preview()
    (text, buttons), = said
    assert buttons is None and "🔒" not in text and "τίποτα να αλλάξει" in text


def test_nonce_names_this_exact_proposal(monkeypatch, public):
    """The ✅ button carries the nonce; apply refuses if the proposal changed meanwhile."""
    g = game(monkeypatch, public, BAD, captain=10)
    first = lineup_cmd.propose(lineup_cmd.load_state())["nonce"]
    assert len(first) == 12 and int(first, 16) >= 0
    assert lineup_cmd.propose(lineup_cmd.load_state())["nonce"] == first, "ίδια δεδομένα, ίδιο nonce"
    pred = json.loads((public / "predictions.json").read_text())
    for p in pred["players"]:
        if p["fantasy_id"] == 5:
            p["x_now"] = 50                          # new data: P5 should now be the captain
    (public / "predictions.json").write_text(json.dumps(pred))
    assert lineup_cmd.propose(lineup_cmd.load_state())["nonce"] != first
    with pytest.raises(lineup_cmd.Abort, match="άλλαξε"):
        lineup_cmd.apply(first)
    assert g.saved == []


def test_load_state_reads_the_game_and_the_predictions(monkeypatch, public):
    game(monkeypatch, public, BAD, captain=10, played={1: 33})
    sq = {p["id"]: p for p in lineup_cmd.load_state()["squad"]}
    assert sq[1]["x_now"] == 33.0 and sq[1]["played"], "όποιος έπαιξε μετράει με τους πραγματικούς πόντους"
    assert sq[5]["x_now"] == 18.0, "οι υπόλοιποι με το xFPT των predictions"
    assert sq[10]["name"] == "P10" and sq[10]["cur_captain"] and sq[10]["turn"] == 2
    assert sq[11]["position"] == "Head Coach" and sq[11]["cur_role"] == "coach"
    assert sq[2]["cur_role"] == "6ος" and sq[9]["cur_role"] == "πάγκος"


def test_a_player_without_a_prediction_counts_zero(monkeypatch, public):
    game(monkeypatch, public, BAD, captain=10)
    pred = json.loads((public / "predictions.json").read_text())
    pred["players"] = [p for p in pred["players"] if p["fantasy_id"] != 4]
    (public / "predictions.json").write_text(json.dumps(pred))
    assert next(p for p in lineup_cmd.load_state()["squad"] if p["id"] == 4)["x_now"] == 0.0


@pytest.mark.parametrize("move", ["into_the_five", "captain"])
def test_the_rail_for_played_players_holds_even_if_the_optimizer_slips(monkeypatch, public, move):
    """The game refuses (422) moving a played player into the six or giving him the armband;
    lineup_cmd checks it itself before writing, whatever the optimizer returns."""
    g = game(monkeypatch, public, GOOD, captain=1, played={9: 2, 7: 1, 5: 3})
    real = lineup_cmd.optimize.defer_later_turns

    def slip(team):
        team, plan = real(team)
        for p in team:
            if move == "into_the_five" and p["id"] in (7, 2):     # played 7 (6ος) <-> unplayed 2
                p["role"] = {7: "5άδα", 2: "6ος"}[p["id"]]
            if move == "captain":
                p["captain"] = p["id"] == 5                       # played, not the captain
        return team, plan
    monkeypatch.setattr(lineup_cmd.optimize, "defer_later_turns", slip)
    with pytest.raises(lineup_cmd.Abort, match="έχει ήδη παίξει"):
        lineup_cmd.propose(lineup_cmd.load_state())
    assert g.saved == []


def test_any_refusal_is_reported_not_only_the_lock(monkeypatch, public):
    for status, reply in ((403, "Forbidden"), (400, "Bad Request")):
        game(monkeypatch, public, BAD, captain=10, status=status, reply=reply)
        pr = lineup_cmd.propose(lineup_cmd.load_state())
        with pytest.raises(lineup_cmd.Abort, match=f"απέρριψε το sub \\({status}\\): {reply}"):
            lineup_cmd.apply(pr["nonce"])


def test_main_runs_the_mode_it_is_given(monkeypatch):
    ran = []
    for name in ("preview", "check", "apply"):
        monkeypatch.setattr(lineup_cmd, name, lambda *a, n=name: ran.append((n, *a)))
    for argv in ([], ["preview"], ["check"], ["apply", "abc"]):
        assert lineup_cmd.main(argv) == 0
    assert ran == [("preview",), ("preview",), ("check",), ("apply", "abc")]
