"""fantasy.rank_of against standings of any size and page size: the rank must not depend on how
many teams the game returns per page (the binary search stops with up to 25 positions left),
and tied teams share a position as the game shows it."""
import base64
import json
import random

import pytest

from elf import fantasy


def fake_standings(monkeypatch, rows, page):
    """rows: [(position, total)] sorted by position; the cursor is base64 JSON of the last position."""
    calls = []

    def get(path, params=None, **k):
        pos = json.loads(base64.b64decode(params["cursor"]))["tms.position"] if "cursor" in params else 0
        calls.append(pos)
        after = [r for r in rows if r[0] > pos][:page]
        return [{"position": p, "total_pts": t, "name": "x"} for p, t in after]
    monkeypatch.setattr(fantasy, "get", get)
    return calls


def true_rank(totals, total):
    return 1 + sum(t > total for t in totals)


@pytest.mark.parametrize("teams", [300, 20000, 25600, 51200])
@pytest.mark.parametrize("page", [25, 20, 10, 50])
def test_rank_is_right_whatever_the_page_size(monkeypatch, teams, page):
    totals = [300.0 - i * 300.0 / teams for i in range(teams)]
    fake_standings(monkeypatch, list(enumerate(totals, 1)), page)
    rnd = random.Random(teams * 100 + page)
    for total in [rnd.uniform(0, 300) for _ in range(15)] + [999.0, -1.0, totals[0], totals[-1]]:
        assert fantasy.rank_of(total, 7, 55, teams) == true_rank(totals, total), (teams, page, total)


def test_few_requests_even_for_a_big_classification(monkeypatch):
    totals = [300.0 - i * 0.001 for i in range(200000)]
    calls = fake_standings(monkeypatch, list(enumerate(totals, 1)), 25)
    fantasy.rank_of(123.4567, 7, 55, 200000)
    assert len(calls) <= 16                          # log2(200000 / 25) + a page or two


def test_tied_teams_share_the_position_the_game_shows(monkeypatch):
    # competition ranking: 1, 2, 2, 4, 5 ...
    rows = [(1, 100.0), (2, 90.0), (2, 90.0), (4, 80.0), (5, 70.0)]
    fake_standings(monkeypatch, rows, 2)
    assert fantasy.rank_of(95.0, 7, 55, 5) == 2      # between 100 and the two 90s
    assert fantasy.rank_of(90.0, 7, 55, 5) == 2      # equal points: the same position
    assert fantasy.rank_of(85.0, 7, 55, 5) == 4      # behind both tied teams
    assert fantasy.rank_of(10.0, 7, 55, 5) == 6


def test_a_team_count_larger_than_the_real_list_is_harmless(monkeypatch):
    totals = [100.0 - i for i in range(40)]
    fake_standings(monkeypatch, list(enumerate(totals, 1)), 25)
    assert fantasy.rank_of(80.5, 7, 55, 5000) == 21       # 100 .. 81 above
    assert fantasy.rank_of(-5.0, 7, 55, 5000) == 41


def test_a_page_that_does_not_move_on_cannot_loop_forever(monkeypatch):
    monkeypatch.setattr(fantasy, "get", lambda path, params=None, **k: [
        {"position": 1, "total_pts": 500.0}])        # the same page for every cursor
    assert fantasy.rank_of(10.0, 7, 55, 1) == 2
