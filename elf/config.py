"""Central configuration: paths, competition constants, model weights."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HISTORY = DATA / "history"      # committed, compressed raw-ish public stats
PUBLIC = DATA / "public"         # derived JSON consumed by dashboard / bot

CURRENT_SEASON = 2026            # EuroLeague 2026-27 -> season code E2026
TIMEZONE = "Europe/Athens"

# Fantasy (Dunkest) game: https://euroleaguefantasy.euroleaguebasketball.net/10
FANTASY_API = "https://fantaking-api.dunkest.com/api/v1"
FANTASY_LEAGUE_ID = 10
SQUAD = {"G": 4, "F": 4, "C": 2}  # + 1 head coach
BUDGET = 100.0
CAPTAIN_MULTIPLIER = 2.0
BENCH_MULTIPLIER = 0.5             # starters (5) + sixth man get 100%

# Model priors. Context coefficients are overwritten by the backtest fit
# (data/public/model_params.json) once it has been run.
MODEL = {
    # form blend (renormalised when a component is missing)
    "w_last3": 0.5,
    "w_season": 0.3,
    "w_prev": 0.2,
    "prev_decay_k": 5,        # prev-season weight *= k / (k + games_this_season)
    # team ratings
    "team_prev_regress": 0.67,  # keep 2/3 of last season's net rating (roster churn)
    "team_blend_k": 8,          # games before current season outweighs prior
    "hca_shrink_k": 20,         # games of evidence before trusting team-specific HCA
    "pos_shrink_k": 10,         # games before trusting position-allowed PIR
    # multiplicative context effects (elasticities)
    "coef": {
        "calib": 0.0,      # overall bias correction
        "pos": 0.4,        # opponent PIR allowed to this position vs league
        "pace": 0.3,       # expected game pace vs league
        "margin": 0.0,     # expected margin for player's team (per 10 pts)
        "blowout": 0.0,    # |expected margin| (per 10 pts), minutes loss
        "home": 0.04,      # playing at home
    },
}
