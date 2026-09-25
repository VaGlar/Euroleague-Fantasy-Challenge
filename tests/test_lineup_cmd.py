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
    assert g.save_roster(1, 500, body).status_code == 422


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
