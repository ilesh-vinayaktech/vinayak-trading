# ruff: noqa: E501
"""ATI x hold signal, variants A and B (2026-11-19). RESEARCH ONLY: B is NOT a change to the frozen paper/product rule (data/research/winner_v2/frozen_HOLD_SIGNAL_V1.json).
Question: does requiring STRONG_UPTREND (algo.ati.regime ati-r1, fixed rules, nothing fitted) at the signal close improve the frozen hold rule?
  A  control   the product rule, via algo.market.hold_signal (31 OHLC features, frozen HGB, rank 0-100): BUY a flat stock at rank >= 90, SELL a held stock at rank <= 20, at the next open.
  B  entry     A, but a BUY needs the stock's rule regime == STRONG_UPTREND at the same close. Exits unchanged.
Not run here: C (exit handling: needs a precise definition first) and D (the model retrained with a regime feature).
Folds, as in the frozen study: test 2022 / 2023 / 2024 with the model trained to the end of 2020 / 2021 / 2022 (the year between is a gap). B has no fitted parameter and no selected threshold, so there is nothing
to fit inside a training window; the rule is the same in every fold and each fold is scored on data after its training end.
LIMITS, stated up front: STRONG_UPTREND was singled out after the regime report saw 2019-2024 (it was the only regime with a positive mean, and it did not survive volatility matching), so 2022-2024 is NOT an untouched
test of B; the untouched years 2025-26 are protected and were already read once for A. Result = development evidence, non-confirmatory; confirmation can only come from forward paper evidence.
Costs: repo DELIVERY schedules + slippage on every trade. Market = the equal-weight average stock over the same open-to-open window. Portfolio reading: at most 10 positions of 1/10 each, highest rank first, cash earns 0.
SUCCESS RULE (fixed before the first run): B beats A only if (1) the pooled paired daily net portfolio return B - A has a 95% stationary-bootstrap CI (block 10 days) entirely above 0, AND (2) B's compounded net
return beats A's in at least 2 of the 3 folds, AND (3) B has at least 300 trades pooled. Fewer than 300 trades = INCONCLUSIVE. Otherwise FAIL.
Data: Kite adjusted bars strictly before 2025-01-01 (protected holdout not read).
usage: study_ati_hold_regime.py [--db URL] [--out FILE]"""

import argparse
import os
import sys
from datetime import date

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, Costs, describe, vec_round_trip

from algo.ati.features import compute_features
from algo.ati.regime import CODE, NEEDED, REGIMES, rule_regimes
from algo.backtest.validation.stats import bootstrap_interval
from algo.market import hold_signal as hs

END, FIRST = "2025-01-01", "2016-01-01"
STRONG = CODE["STRONG_UPTREND"]
NMAX = 10
FOLD_YEARS = (2022, 2023, 2024)
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db) as conn:
    ids = hs.universe(conn)
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source='kite' AND instrument_id = ANY(%s) AND ts >= %s AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC",
        (ids, FIRST, END),
    ).fetchall()
    costs = Costs(conn)
    cost_line = describe(costs)
d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
del rows
d["d"] = pd.to_datetime(d["d"])
bars = {int(i): g.set_index("d").drop(columns="iid").sort_index() for i, g in d.groupby("iid")}
panel = {
    k: d.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c", "v")
}
del d
dates = panel["c"].index
iids = panel["c"].columns
O, H, LO, C, V = (panel[k].to_numpy(dtype="float64") for k in ("o", "h", "l", "c", "v"))  # noqa: E741
TV = pd.DataFrame(C * V).rolling(20, min_periods=5).mean().to_numpy()
T, S = O.shape
d64 = dates.to_numpy()
# regimes (known at each close) and the market series
f = {
    m.name: x
    for m, x in compute_features(O, H, LO, C, np.zeros_like(V), ("trend", "momentum", "volatility"))
    if m.name in set(NEEDED)
}
G = rule_regimes(f)
del f
with np.errstate(invalid="ignore", divide="ignore"):
    step = np.vstack([O[1:] / O[:-1] - 1, np.full((1, S), np.nan)])  # open(t) -> open(t+1)
mkt_step = np.nanmean(step, axis=1)
CI = np.concatenate(
    [[0.0], np.cumsum(np.log1p(np.nan_to_num(mkt_step[:-1])))]
)  # CI[t] = log of the market's open(0) -> open(t)
rows_all = hs.assemble(hs.feature_frames(bars), with_target=True)
del bars


def simulate(R: np.ndarray, t0: int, t1: int, strong_only: bool) -> pd.DataFrame:
    """The state machine on days t0..t1 (signal at close t, trade at open t+1): one row per trade (positions still open are marked at open t1+1)."""
    in_pos, ent = np.zeros(S, bool), np.full(S, -1)
    rec = []
    for t in range(t0, t1 + 1):
        r = R[t]
        with np.errstate(invalid="ignore"):
            sell = in_pos & (r <= hs.SELL_AT)
            buy = ~in_pos & (r >= hs.BUY_AT)
        if strong_only:
            buy &= G[t] == STRONG
        for j in np.flatnonzero(sell):
            rec.append((j, ent[j], t + 1, G[ent[j] - 1, j]))
        in_pos &= ~sell
        in_pos |= buy
        ent[buy] = t + 1
    for j in np.flatnonzero(in_pos):
        rec.append((j, ent[j], t1 + 1, G[ent[j] - 1, j]))
    tr = pd.DataFrame(rec, columns=["j", "e", "x", "reg"])
    tr = tr[tr["x"] > tr["e"]].reset_index(drop=True)
    tr["pe"], tr["px"] = O[tr["e"], tr["j"]], O[tr["x"], tr["j"]]
    tr = tr[np.isfinite(tr["pe"]) & np.isfinite(tr["px"])].reset_index(drop=True)
    tr["gross"] = tr["px"] / tr["pe"] - 1
    tr["cost"] = vec_round_trip(
        costs, d64[tr["e"]], d64[tr["x"]], TV[tr["e"] - 1, tr["j"]], TV[tr["x"] - 1, tr["j"]]
    )
    tr["net"] = tr["gross"] - tr["cost"]
    tr["mkt"] = np.exp(CI[tr["x"]] - CI[tr["e"]]) - 1
    tr["xs"] = tr["net"] - tr["mkt"]
    tr["hold"] = tr["x"] - tr["e"]
    return tr.sort_values("e").reset_index(drop=True)


def portfolio(R: np.ndarray, t0: int, t1: int, strong_only: bool) -> pd.DataFrame:
    """Equal-weight portfolio, at most NMAX positions of 1/NMAX each, highest rank first; day t earns open(t) -> open(t+1) on what was held, costs charged on the trade day."""
    held = np.zeros(S, bool)
    w = 1.0 / NMAX
    out = []
    for t in range(t0, t1 + 1):
        day = w * np.nansum(np.where(held, step[t], 0.0))
        r, day_t = R[t], pd.Timestamp(d64[t + 1]).date()
        with np.errstate(invalid="ignore"):
            sells = held & (r <= hs.SELL_AT)
            cand = ~held & (r >= hs.BUY_AT)
        if strong_only:
            cand &= G[t] == STRONG
        cost = sum(
            w * (costs.charges(day_t, "SELL") + costs.slip(TV[t, j])) for j in np.flatnonzero(sells)
        )
        held &= ~sells
        pick = np.flatnonzero(cand)
        pick = pick[np.argsort(-r[pick])][: NMAX - int(held.sum())]
        cost += sum(w * (costs.charges(day_t, "BUY") + costs.slip(TV[t, j])) for j in pick)
        held[pick] = True
        out.append((pd.Timestamp(d64[t]), day - cost, held.sum() / NMAX, mkt_step[t]))
    return pd.DataFrame(out, columns=["day", "ret", "exposure", "mkt"]).set_index("day")


def ci_of(x: pd.Series | np.ndarray, block: float = 20) -> str:
    s = [float(v) for v in np.asarray(x) if np.isfinite(v)]
    iv = (
        bootstrap_interval(s, lambda xs: sum(xs) / len(xs), n_boot=500, mean_block=block, seed=0)
        if len(s) > 30
        else None
    )
    return f"{iv.point * 100:+.3f} [{iv.low * 100:+.3f}, {iv.high * 100:+.3f}]" if iv else "n/a"


out = [
    "# ATI x hold signal: A (frozen rule) vs B (entry only in STRONG_UPTREND)",
    f"universe {S} liquid stocks, bars before {END}; {cost_line}",
    "",
]
trades: dict[str, list[pd.DataFrame]] = {"A": [], "B": []}
ports: dict[str, list[pd.DataFrame]] = {"A": [], "B": []}
fold_rows = []
for year in FOLD_YEARS:
    train_end = hs.train_end_for(date(year, 1, 1))
    X, y = hs.training_set(rows_all, train_end)
    model = hs.fit(X, y)
    test = rows_all[
        (rows_all["date"] >= pd.Timestamp(year, 1, 1))
        & (rows_all["date"] <= pd.Timestamp(year, 12, 31))
    ]
    sc = hs.score(model, test)
    R = (
        sc.pivot(index="day", columns="iid", values="rank_pct")
        .reindex(index=dates, columns=iids)
        .to_numpy()
    )
    days_idx = np.flatnonzero(np.isfinite(R).any(1))
    t0, t1 = int(days_idx[0]), int(days_idx[-1])
    for name, strong in (("A", False), ("B", True)):
        tr, pf = simulate(R, t0, t1, strong), portfolio(R, t0, t1, strong)
        trades[name].append(tr.assign(year=year))
        ports[name].append(pf.assign(year=year))
        fold_rows.append(
            (
                year,
                name,
                len(tr),
                tr["hold"].mean(),
                tr["gross"].mean() * 100,
                tr["net"].mean() * 100,
                tr["xs"].mean() * 100,
                (1 + pf["ret"]).prod() * 100 - 100,
                (1 + pf["mkt"]).prod() * 100 - 100,
                pf["exposure"].mean(),
            )
        )
out.append("## Per fold (test year; model trained to the end of the year two before it)")
out.append("")
out.append(
    pd.DataFrame(
        fold_rows,
        columns=[
            "year",
            "variant",
            "trades",
            "mean_hold",
            "gross%",
            "net%",
            "net-market%",
            "portfolio%",
            "market%",
            "exposure",
        ],
    )
    .round(3)
    .to_string(index=False)
)
out += [
    "",
    "## Pooled 2022-2024: per-trade net return minus the market over the trade window, %, mean [95% CI over trades in time order]",
    "",
]
for name in ("A", "B"):
    tr = pd.concat(trades[name])
    out.append(
        f"{name}: trades {len(tr)}, mean hold {tr['hold'].mean():.1f} sessions, net-market {ci_of(tr['xs'])}"
    )
pa, pb = pd.concat(ports["A"]), pd.concat(ports["B"])
diff = (pb["ret"] - pa["ret"]).to_numpy()
out += [
    "",
    "## Portfolio (max 10 positions, cash earns 0): daily net return, %",
    "",
    f"A daily {ci_of(pa['ret'], 10)}  (exposure {pa['exposure'].mean():.2f})",
    f"B daily {ci_of(pb['ret'], 10)}  (exposure {pb['exposure'].mean():.2f})",
    f"B - A daily {ci_of(diff, 10)}",
]
folds_b_wins = sum(
    (1 + pb[pb["year"] == y]["ret"]).prod() > (1 + pa[pa["year"] == y]["ret"]).prod()
    for y in FOLD_YEARS
)
iv = bootstrap_interval(
    [float(v) for v in diff], lambda xs: sum(xs) / len(xs), n_boot=500, mean_block=10, seed=0
)
n_b = sum(len(t) for t in trades["B"])
verdict = (
    "INCONCLUSIVE"
    if n_b < 300
    else ("PASS" if (iv and iv.low > 0 and folds_b_wins >= 2) else "FAIL")
)
out += ["", "## Diagnostic: A's own trades split by the regime at their entry signal (pooled)", ""]
dg = (
    pd.concat(trades["A"])
    .groupby("reg")["xs"]
    .agg(["size", "mean"])
    .rename(index={i: REGIMES[i] for i in range(7)})
)
dg["mean"] *= 100
out.append(dg.rename(columns={"size": "trades", "mean": "net-market%"}).round(3).to_string())
out += [
    "",
    f"## Verdict on the frozen rule: {verdict}  (folds where B beats A: {folds_b_wins}/3; B trades pooled: {n_b}; B - A daily CI lower bound {iv.low * 100 if iv else float('nan'):+.4f}%). Development evidence only, non-confirmatory.",
]
text = "\n".join(out)
if a.out:
    open(a.out, "w").write(text + "\n")
print(text)
