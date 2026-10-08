"""The repo is public: the article archive and the owner's data live in the private data repo
(elf-data), the update keeps the two in step (update.yml). These guard that setup:
the private-file list agrees in its three places, the workflow steps run in the right order and
only with the secret, and what the repo tracks right now holds nothing private."""
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from elf import publish

from conftest import REPO

WORKFLOWS = REPO / ".github" / "workflows"


def steps(workflow: str) -> list[dict]:
    d = yaml.safe_load((WORKFLOWS / workflow).read_text())
    return list(d["jobs"].values())[0]["steps"]


def index(st: list[dict], needle: str) -> int:
    hits = [i for i, s in enumerate(st) if needle in (s.get("name") or "")]
    assert len(hits) == 1, f"step «{needle}»: {len(hits)} matches"
    return hits[0]


def tracked(*paths: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", *paths], cwd=REPO, capture_output=True, text=True,
                         check=True).stdout
    return [line for line in out.splitlines() if line]


# ------------------------------------------------------------------ one list, three places

def test_private_files_agree_in_publish_workflow_and_gitignore():
    private = {"data/archive"} | {f"data/public/{n}" for n in publish.PRIVATE_ONLY}
    run = next(s["run"] for s in steps("update.yml") if s.get("name") == "Sanitize for the public repo")
    untracked = set(re.findall(r"data/[\w/.]+", run.split("git rm", 1)[1]))
    assert untracked == private, "update.yml stops tracking a different list than publish.PRIVATE_ONLY"
    ignored = {line.strip().rstrip("/") for line in (REPO / ".gitignore").read_text().splitlines()}
    assert private <= ignored, f"not in .gitignore: {sorted(private - ignored)}"


def test_every_data_public_file_is_either_published_sanitized_or_private_or_known():
    """A new output file must be placed on purpose: sanitized for the public repo (PUBLIC_FILES),
    private (PRIVATE_ONLY) or explicitly harmless (below). Otherwise it would go public as is."""
    harmless = {"prices.csv", "pred_log.csv", "expert_log.csv", "report_public.json",
                "clubs.json", "model_params.json", "players.json",
                "sent.json"}         # only the date and time the day's report went out
    known = set(publish.PUBLIC_FILES) | set(publish.PRIVATE_ONLY) | harmless
    written = set(re.findall(r'_write\("([\w.]+)"', (REPO / "elf" / "run.py").read_text()))
    written |= set(re.findall(r'PUBLIC / "([\w.]+)"', "".join(
        p.read_text() for p in (REPO / "elf").glob("*.py"))))
    assert written - known == set(), f"place these on purpose (publish.py): {sorted(written - known)}"


# ------------------------------------------------------------------ the workflow

def test_update_restores_checks_saves_then_sanitizes_then_commits():
    st = steps("update.yml")
    order = [index(st, n) for n in ("Private data repo", "Restore the private data", "Pipeline",
                                     "Data check", "Save the private data", "Sanitize for the public repo",
                                     "Commit data", "Build site")]
    assert order == sorted(order), "the data check must see the full files, and nothing private " \
                                   "may be committed before it is saved and sanitized"


def test_private_steps_need_the_secret_and_writes_need_the_live_branch():
    st = steps("update.yml")
    for name in ("Private data repo", "Restore the private data", "Save the private data",
                 "Sanitize for the public repo"):
        assert "HAS_DATA_REPO" in st[index(st, name)]["if"], name
    for name in ("Save the private data", "Sanitize for the public repo", "Commit data"):
        assert "env.LIVE == 'true'" in st[index(st, name)]["if"], f"{name}: a preview must write nothing"
    env = yaml.safe_load((WORKFLOWS / "update.yml").read_text())["jobs"]["update"]["env"]
    assert "secrets.DATA_REPO_TOKEN" in env["HAS_DATA_REPO"]


def test_the_personal_site_and_the_final_note_read_the_full_files():
    st = steps("update.yml")
    assert "private/public" in st[index(st, "Build site")]["run"]
    assert "private/public/predictions.json" in st[index(st, "Notify Telegram")]["run"]


def test_lineup_restores_the_owners_team_before_it_runs():
    st = steps("lineup.yml")
    assert index(st, "Restore the private data") < index(st, "Lineup")
    assert "HAS_DATA_REPO" in st[index(st, "Restore the private data")]["if"]


def test_the_report_is_not_printed_to_the_public_actions_log(monkeypatch, capsys):
    from elf import run
    src = (REPO / "elf" / "run.py").read_text()
    main = src.split('if __name__ == "__main__":', 1)[1]
    monkeypatch.setattr("sys.argv", ["run"])
    secret = "Προτεινόμενη πεντάδα: OWNER LINEUP"
    exec(main.replace("\n    ", "\n").strip(), {**vars(run), "build": lambda offline: {
        "messages": [{"date": "d", "turn": 1, "text": secret}]}})
    out = capsys.readouterr().out
    assert secret not in out and "1 message" in out


# ------------------------------------------------------------------ what the repo holds now

def test_the_repo_tracks_no_archive_and_no_private_file():
    assert tracked("data/archive") == []
    for name in publish.PRIVATE_ONLY:
        assert tracked(f"data/public/{name}") == [], name


def test_the_repos_data_is_the_sanitized_copy():
    """Fails if an update ever commits the full files here (e.g. the secret went missing)."""
    pub = REPO / "data" / "public"
    # booleans only: pytest prints the compared values on failure, and the log is public
    pred = json.loads((pub / "predictions.json").read_text())
    has_team, has_health = pred.get("my_team") is not None, bool(pred.get("health"))
    assert not has_team, "predictions.json: my_team in the public repo"
    assert not has_health, "predictions.json: health in the public repo"
    news = json.loads((pub / "news.json").read_text())
    has_text = any("text" in a for a in news.get("articles", []))
    assert not has_text, "news.json: articles' text in the public repo"
    if (pub / "tracking.json").exists():
        has_lineups = bool(json.loads((pub / "tracking.json").read_text()).get("lineups"))
        assert not has_lineups, "tracking.json: lineups in the public repo"
    if (pub / "autopilot.json").exists():
        rounds = json.loads((pub / "autopilot.json").read_text()).get("rounds", [])
        has_mine = any("my_pts" in r or "my_rank" in r for r in rounds)
        assert not has_mine, "autopilot.json: the owner's points/rank in the public repo"


@pytest.mark.parametrize("name", ["news.json", "report.json"])
def test_ui_fixtures_hold_no_article_text_and_no_personal_report(name):
    fx = json.loads((REPO / "tests" / "ui" / "fixtures" / name).read_text())
    if name == "news.json":
        assert all("text" not in a for a in fx["articles"])
    else:
        public = json.loads((REPO / "tests" / "ui" / "fixtures" / "report_public.json").read_text())
        assert fx == public, "the UI fixture report is the public one (the personal one lists the owner's trades)"
