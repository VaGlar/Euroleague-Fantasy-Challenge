"""The defences' total PIR allowed (shown in «Άμυνες», not used by the model: R&D 024)."""
import pandas as pd

from elf import model


def box(rows):
    return pd.DataFrame(rows, columns=["gamecode", "team", "person_id", "pir"])


def test_total_allowed_is_the_opponents_pir_vs_the_league_shrunk_to_last_season():
    # this season: A gave 100 per game (B scored 60+40), B gave 60 (A scored 30+30): league mean 80
    cur = box([(1, "A", "a1", 30), (1, "A", "a2", 30), (1, "B", "b1", 60), (1, "B", "b2", 40)])
    empty = box([])
    dev = model.total_allowed(cur, empty, {"pos_shrink_k": 0})     # no shrink: the raw deviations
    assert round(dev["A"], 3) == 0.25 and round(dev["B"], 3) == -0.25
    shrunk = model.total_allowed(cur, empty, {"pos_shrink_k": 10})  # 1 game vs k=10, no last season: ~0
    assert abs(shrunk["A"]) < 0.03


def test_total_allowed_without_any_game_is_empty():
    assert model.total_allowed(box([]), box([]), {"pos_shrink_k": 10}) == {}
