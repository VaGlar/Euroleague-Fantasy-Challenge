"""R&D 021 — the price as memory for players with few games: live (newcomers only) vs everyone, on the
predictions logged before tip-off (pred_log.csv) against the real points.

python research/021_price_prior/run.py <dir with pred_log.csv, prices.csv, players_2025/2026.csv.gz, games_2026.csv.gz>
(e.g. files from `git show origin/main:data/...`). Round in R below."""
import numpy as np, pandas as pd, sys
T = sys.argv[1]
pl = pd.read_csv(f"{T}/pred_log.csv", dtype={"person_id": str})
pr = pd.read_csv(f"{T}/prices.csv", dtype={"person_id": str})
b26 = pd.read_csv(f"{T}/players_2026.csv.gz", dtype={"person_id": str})
b25 = pd.read_csv(f"{T}/players_2025.csv.gz", dtype={"person_id": str})
g26 = pd.read_csv(f"{T}/games_2026.csv.gz")
R = 2
games = g26[(g26["round"] == R) & g26["played"]]
won = {}
for x in games.itertuples():
    won[(x.gamecode, x.home)] = x.home_score > x.away_score
    won[(x.gamecode, x.away)] = x.away_score > x.home_score
d = pl[(pl["round"] == R) & pl["gamecode"].isin(games["gamecode"])].copy()
box = b26.set_index(["gamecode", "person_id"])
def actual(r):
    k = (r.gamecode, r.person_id)
    if k not in box.index: return 0.0, False
    row = box.loc[k]
    return float(row["pir"]) * (1.1 if won.get((r.gamecode, row["team"])) else 1.0), True
_a = [actual(r) for r in d.itertuples()]; d["actual"] = [float(a) for a, _ in _a]; d["played"] = [bool(p) for _, p in _a]
r1 = set(g26.loc[g26["round"] < R, "gamecode"])
d["g"] = d["person_id"].map(b26[b26["gamecode"].isin(r1)].groupby("person_id").size()).fillna(0)
d["prev"] = d["person_id"].isin(set(b25["person_id"]))
p = pr[pr["matchday"] <= R].sort_values("matchday").groupby("person_id").last()
d["price"] = d["person_id"].map(p["price"]); d["pos"] = d["person_id"].map(p["position"])
d = d[d["price"].notna() & (d["pos"] != "Head Coach")]
d["est"] = np.nan
for pos, g in d[d["x_pred"] > 0].groupby("pos"):
    if len(g) < 10: continue
    s, i = np.polyfit(g["price"], g["x_pred"], 1)
    m = d["pos"] == pos
    d.loc[m, "est"] = (s * d.loc[m, "price"] + i).clip(lower=0)
K = 2
def variant(scope):
    x = d["x_pred"].copy()
    nd = (d["g"] == 0) & ~d["prev"] & d["est"].notna()
    x[nd] = 0.8 * d.loc[nd, "est"]
    m = d["g"].between(1, 10) & d["est"].notna() & (scope if scope is not None else True)
    x[m] = (d.loc[m, "g"] * x[m] + K * d.loc[m, "est"]) / (d.loc[m, "g"] + K)
    return x
V = {"χωρίς τιμή": variant(pd.Series(False, index=d.index)),
     "live (μόνο νέοι)": variant(~d["prev"]),
     "dev (όλοι 1–10)": variant(None)}
def stats(mask, label):
    print(f"\n{label}: n={int(mask.sum())}")
    for k, x in V.items():
        e = x[mask] - d.loc[mask, "actual"]
        print(f"  {k:18s} MAE {e.abs().mean():5.2f}  bias {e.mean():+5.2f}  corr {np.corrcoef(x[mask].astype(float), d.loc[mask,'actual'].astype(float))[0,1]:.3f}")
stats(pd.Series(True, index=d.index), "Όλοι (και όσοι δεν έπαιξαν = 0)")
stats(d["played"], "Όσοι έπαιξαν")
ch = (V["dev (όλοι 1–10)"] - V["live (μόνο νέοι)"]).abs() > 0.05
stats(ch & d["played"], "Μόνο όσοι άλλαξαν live→dev και έπαιξαν")
up = ch & (V["dev (όλοι 1–10)"] > V["live (μόνο νέοι)"])
stats(up & d["played"], "…που ανέβηκαν")
stats(ch & ~up & d["played"], "…που έπεσαν")
x = V["dev (όλοι 1–10)"]
for nm in ["MOTLEY", "JONES, CARLIK", "LESSORT", "TUBELIS", "NTILIKINA", "COLSON", "BACON"]:
    m = d["name"].str.contains(nm)
    for i in d[m].index:
        print(f"{d.at[i,'name'][:22]:22s} live {V['live (μόνο νέοι)'][i]:5.1f}  dev {x[i]:5.1f}  actual {d.at[i,'actual']:5.1f}")
