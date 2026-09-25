"""/lineup end to end against a fake game: propose -> apply -> read back."""
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


def test_turn2_morning_played_players_are_never_moved(monkeypatch, public):
    # all starters played in T1: the game forbids any move, so nothing is sent
    g = game(monkeypatch, public, GOOD, captain=1, played=T1_PTS)
    pr = lineup_cmd.propose(lineup_cmd.load_state())
    assert pr["changes"] == []
    lineup_cmd.apply(pr["nonce"])
    assert g.saved == []


def test_turn2_morning_swaps_only_unplayed_and_keeps_played_slots(monkeypatch, public):
    roles = {**GOOD, 7: "πάγκος", 4: "6ος"}          # T2 guard 4 (xPTS 3) is sixth man
    g = game(monkeypatch, public, roles, captain=1, played=T1_PTS)
    before = {p["id"]: p["court_position"] for p in g.state["players"]}
    pr = lineup_cmd.propose(lineup_cmd.load_state())
    assert {p["id"] for p in pr["changes"]} == {4, 10}
    lineup_cmd.apply(pr["nonce"])
    after = {p["id"]: p["court_position"] for p in g.state["players"]}
    assert all(after[i] == before[i] for i in T1_PTS), "όσοι έπαιξαν κρατούν την ίδια θέση"
    new_roles, cap = g.lineup()
    assert new_roles[10] == "6ος" and new_roles[4] == "πάγκος" and cap == 1


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
