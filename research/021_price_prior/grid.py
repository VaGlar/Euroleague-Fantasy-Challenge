"""R&D 021b — the price memory's weight after Round 3: K0 (weight after the 1st game) and decay (×per game)
on Rounds 2 + 3. The logged predictions already carry the live rule (R2: K=2 for newcomers only; R3: 2·0.5^(g-1)
for everyone with 1-12 games), so it is taken out first (raw = ((g+k)x − k·est)/g, est re-fitted as live:
price → xFPT per position), then each (K0, decay) is applied to the raw model. Out by the news (x = 0) stays 0.

python research/021_price_prior/grid.py <dir with pred_log.csv, prices.csv, players_2025/2026.csv.gz, games_2026.csv.gz>"""
import numpy as np, pandas as pd, sys
T = sys.argv[1]
pl = pd.read_csv(f"{T}/pred_log.csv", dtype={"person_id": str})
pr = pd.read_csv(f"{T}/prices.csv", dtype={"person_id": str})
b26 = pd.read_csv(f"{T}/players_2026.csv.gz", dtype={"person_id": str})
b25 = pd.read_csv(f"{T}/players_2025.csv.gz", dtype={"person_id": str})
g26 = pd.read_csv(f"{T}/games_2026.csv.gz")
prev = set(b25["person_id"])
box = b26.set_index(["gamecode", "person_id"])


def round_frame(R, live):
    games = g26[(g26["round"] == R) & g26["played"]]
    won = {}
    for x in games.itertuples():
        won[(x.gamecode, x.home)] = x.home_score > x.away_score
        won[(x.gamecode, x.away)] = x.away_score > x.home_score
    d = pl[(pl["round"] == R) & pl["gamecode"].isin(games["gamecode"])].copy()
    act = []
    for r in d.itertuples():
        k = (r.gamecode, r.person_id)
        if k in box.index:
            row = box.loc[k]
            act.append((float(row["pir"]) * (1.1 if won.get((r.gamecode, row["team"])) else 1.0), True))
        else:
            act.append((0.0, False))
    d["actual"] = [a for a, _ in act]; d["played"] = [p for _, p in act]
    before = set(g26.loc[g26["round"] < R, "gamecode"])
    d["g"] = d["person_id"].map(b26[b26["gamecode"].isin(before)].groupby("person_id").size()).fillna(0)
    d["prev"] = d["person_id"].isin(prev)
    p = pr[pr["matchday"] <= R].sort_values("matchday").groupby("person_id").last()
    d["price"] = d["person_id"].map(p["price"]); d["pos"] = d["person_id"].map(p["position"])
    d = d[d["price"].notna() & (d["pos"] != "Head Coach")].copy()
    d["est"] = np.nan
    for pos, g in d[d["x_pred"] > 0].groupby("pos"):
        if len(g) < 10: continue
        s, i = np.polyfit(g["price"], g["x_pred"], 1)
        m = d["pos"] == pos
        d.loc[m, "est"] = (s * d.loc[m, "price"] + i).clip(lower=0)
    # take the live rule out
    k = live(d)
    m = (k > 0) & (d["g"] > 0) & d["est"].notna() & (d["x_pred"] > 0)
    d["raw"] = d["x_pred"].astype(float)
    d.loc[m, "raw"] = (((d.loc[m, "g"] + k[m]) * d.loc[m, "x_pred"] - k[m] * d.loc[m, "est"]) / d.loc[m, "g"]).clip(lower=0)
    d["R"] = R
    return d


live2 = lambda d: np.where(~d["prev"] & d["g"].between(1, 10), 2.0, 0.0)              # R2: newcomers, K=2
live3 = lambda d: np.where(d["g"].between(1, 12), 2.0 * 0.5 ** (d["g"] - 1), 0.0)      # R3: everyone
D = pd.concat([round_frame(2, live2), round_frame(3, live3)], ignore_index=True)
D = D[D["g"] >= 1]                                      # with games this season (no-data newcomers: price only)


def apply(K0, dec):
    k = np.where(D["g"].between(1, 12) & D["est"].notna(), K0 * dec ** (D["g"] - 1), 0.0)
    x = (D["g"] * D["raw"] + k * D["est"].fillna(0)) / (D["g"] + k)
    return np.where(D["x_pred"] <= 0, 0.0, x)          # out by the news stays out


def stat(x, m):
    e = x[m] - D.loc[m, "actual"]
    return e.abs().mean(), e.mean(), int(m.sum())


played = D["played"].values
print("n:", {r: int(((D["R"] == r) & D["played"]).sum()) for r in (2, 3)}, "played, with 1+ games before")
rows = []
for K0 in (0, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 12):
    for dec in (0.25, 0.5, 0.75, 1.0):
        x = apply(K0, dec)
        out = {"K0": K0, "decay": dec}
        for lab, m in (("all", played), ("R2", played & (D["R"] == 2).values), ("R3", played & (D["R"] == 3).values),
                       ("new", played & ~D["prev"].values), ("old", played & D["prev"].values)):
            mae, bias, n = stat(x, m)
            out[f"{lab}_mae"], out[f"{lab}_bias"] = round(mae, 3), round(bias, 2)
        rows.append(out)
        if K0 == 0: break
res = pd.DataFrame(rows).sort_values("all_mae")
pd.set_option("display.width", 200)
print(res.head(12).to_string(index=False))
print("\nlive now (2, 0.5):", res[(res.K0 == 2) & (res.decay == 0.5)][["all_mae", "R2_mae", "R3_mae", "new_mae", "old_mae"]].to_string(index=False))
print("no price  (0):    ", res[res.K0 == 0][["all_mae", "R2_mae", "R3_mae", "new_mae", "old_mae"]].to_string(index=False))
best = res.iloc[0]
xb, xl, x0 = apply(best.K0, best.decay), apply(2, 0.5), apply(0, 1)
for nm in ("MOTLEY", "JONES, CHRIS", "TUBELIS", "BACON"):
    for i in np.where(D["name"].str.contains(nm, case=False).values)[0]:
        r = D.iloc[i]
        print(f"{r['name'][:22]:22s} R{r.R} g={int(r.g)} price {r.price:4.1f} raw {r.raw:5.1f} est {r.est:5.1f} | "
              f"none {x0[i]:5.1f} live {xl[i]:5.1f} best {xb[i]:5.1f} | actual {r.actual:5.1f}{'' if r.played else ' (dnp)'}")

# newcomers and returning players apart (the gain is the newcomers'; the returning lose a little)
print("\nsplit: K0 new / K0 old (decay 0.5)")
for kn in (2, 4, 6, 8):
    for ko in (0, 1, 2):
        k0 = np.where(D["prev"], ko, kn)
        k = np.where(D["g"].between(1, 12) & D["est"].notna(), k0 * 0.5 ** (D["g"] - 1), 0.0)
        x = np.where(D["x_pred"] <= 0, 0.0, (D["g"] * D["raw"] + k * D["est"].fillna(0)) / (D["g"] + k))
        print(f"  new {kn} old {ko}: all {stat(x, played)[0]:.3f}  new {stat(x, played & ~D['prev'].values)[0]:.3f}  old {stat(x, played & D['prev'].values)[0]:.3f}")
