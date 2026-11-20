# ruff: noqa: E501
"""TIE kill test (2026-11-19): does any simple causal trend measure improve the frozen hold rule as an ENTRY filter? RESEARCH ONLY: not a change to data/research/winner_v2/frozen_HOLD_SIGNAL_V1.json.
Control A = the product rule via algo.market.hold_signal (BUY a flat stock at rank >= 90, SELL a held stock at rank <= 20, at the next open). Each variant = A, but a BUY also needs the filter true at the signal close. Exits unchanged.
Filters (every threshold fixed here, BEFORE the first run; nothing fitted, nothing tuned):
  ST      SuperTrend(ATR 10, x3.0) direction up                      (algo.ati.features.supertrend)
  ER      Kaufman efficiency ratio over 20 sessions >= 0.30          (direction-free: chop vs trend)
  SLOPE   20-session regression slope / ATR14 > 0                    (direction)
  SWING   confirmed swings (k=3): higher high AND higher low         (pivot usable only 3 bars after it forms)
  WEEKLY  last completed week's close above its 10-week average
  ALL     all five at once
Folds, as in the frozen study: test 2022 / 2023 / 2024, model trained to the end of 2020 / 2021 / 2022. Same data, costs, portfolio (max 10 x 1/10, cash 0) as study_ati_hold_regime.py.
SUCCESS RULE (fixed before the first run): a filter beats A only if (1) the pooled paired daily net return difference has a 99% stationary-bootstrap CI (block 10 days) entirely above 0 (99% not 95%: six filters are tested),
AND (2) it beats A's compounded net return in at least 2 of 3 folds, AND (3) it has at least 300 pooled trades. Under 300 trades = INCONCLUSIVE. Otherwise FAIL. A PASS here only earns a proper study; it is not evidence of an edge.
LIMITS: 2022-2024 is development data already seen by earlier ATI studies; the protected 2025-26 holdout is NOT read. The diagnostic split of A's trades is descriptive only and is never a candidate filter (do not fit an inverse filter).
usage: study_tie_hold_filters.py [--db URL] [--out FILE]"""

import argparse
import os
import sys
from datetime import date

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, Costs, describe, vec_round_trip

from algo.ati import tie
from algo.ati.features import supertrend
from algo.backtest.validation.stats import bootstrap_interval
from algo.market import hold_signal as hs

END, FIRST = "2025-01-01", "2016-01-01"
NMAX = 10
FOLD_YEARS = (2022, 2023, 2024)
CONF = 0.99
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
# filters, each known at the close of its row (tests/unit/ati/test_tie.py proves prefix invariance)
st_dir, _ = supertrend(H, LO, C, tie.atr(H, LO, C, 10), 3.0)
with np.errstate(invalid="ignore"):
    MASKS: dict[str, np.ndarray] = {
        "ST": st_dir == 1,
        "ER": tie.efficiency_ratio(C, 20) >= 0.30,
        "SLOPE": tie.regression_slope_atr(C, tie.atr(H, LO, C, 14), 20) > 0,
        "SWING": tie.swing_structure(H, LO, 3) == 1,
        "WEEKLY": tie.weekly_trend(C, dates, 10) == 1,
    }
MASKS["ALL"] = np.logical_and.reduce(list(MASKS.values()))
VARIANTS: dict[str, np.ndarray | None] = {"A": None, **MASKS}
with np.errstate(invalid="ignore", divide="ignore"):
    step = np.vstack([O[1:] / O[:-1] - 1, np.full((1, S), np.nan)])  # open(t) -> open(t+1)
mkt_step = np.nanmean(step, axis=1)
CI = np.concatenate([[0.0], np.cumsum(np.log1p(np.nan_to_num(mkt_step[:-1])))])
rows_all = hs.assemble(hs.feature_frames(bars), with_target=True)
del bars


def simulate(R: np.ndarray, t0: int, t1: int, mask: np.ndarray | None) -> pd.DataFrame:
    """The state machine on days t0..t1 (signal at close t, trade at open t+1): one row per trade (open positions marked at open t1+1)."""
    in_pos, ent = np.zeros(S, bool), np.full(S, -1)
    rec = []
    for t in range(t0, t1 + 1):
        r = R[t]
        with np.errstate(invalid="ignore"):
            sell = in_pos & (r <= hs.SELL_AT)
            buy = ~in_pos & (r >= hs.BUY_AT)
        if mask is not None:
            buy &= mask[t]
        for j in np.flatnonzero(sell):
            rec.append((j, ent[j], t + 1))
        in_pos &= ~sell
        in_pos |= buy
        ent[buy] = t + 1
    for j in np.flatnonzero(in_pos):
        rec.append((j, ent[j], t1 + 1))
    tr = pd.DataFrame(rec, columns=["j", "e", "x"])
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
    for k, m in MASKS.items():  # filter state at the entry signal (descriptive diagnostic)
        tr[k] = m[tr["e"] - 1, tr["j"]]
    return tr.sort_values("e").reset_index(drop=True)


def portfolio(R: np.ndarray, t0: int, t1: int, mask: np.ndarray | None) -> pd.DataFrame:
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
        if mask is not None:
            cand &= mask[t]
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


def ci_of(x: pd.Series | np.ndarray, block: float = 20, conf: float = 0.95) -> tuple[str, float]:
    s = [float(v) for v in np.asarray(x) if np.isfinite(v)]
    iv = (
        bootstrap_interval(s, lambda xs: sum(xs) / len(xs), n_boot=500, mean_block=block, confidence=conf, seed=0)
        if len(s) > 30
        else None
    )
    if not iv:
        return "n/a", float("nan")
    return f"{iv.point * 100:+.3f} [{iv.low * 100:+.3f}, {iv.high * 100:+.3f}]", iv.low


trades: dict[str, list[pd.DataFrame]] = {k: [] for k in VARIANTS}
ports: dict[str, list[pd.DataFrame]] = {k: [] for k in VARIANTS}
for year in FOLD_YEARS:
    X, y = hs.training_set(rows_all, hs.train_end_for(date(year, 1, 1)))
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
    for name, m in VARIANTS.items():
        trades[name].append(simulate(R, t0, t1, m).assign(year=year))
        ports[name].append(portfolio(R, t0, t1, m).assign(year=year))
    print("fold", year, "done", file=sys.stderr)

pa = pd.concat(ports["A"])


def fold_wins(pv: pd.DataFrame) -> int:
    return sum(
        (1 + pv[pv["year"] == y]["ret"]).prod() > (1 + pa[pa["year"] == y]["ret"]).prod()
        for y in FOLD_YEARS
    )


out = [
    "# TIE kill test: frozen hold rule (A) with one causal trend filter on entry",
    f"universe {S} liquid stocks, bars before {END}; {cost_line}",
    "",
    "## Pooled 2022-2024 (portfolio: max 10 positions, cash 0; daily net return %, mean [CI]); verdict uses the 99% CI of variant - A",
    "",
]
tbl, verdicts = [], {}
for name in VARIANTS:
    tr, pv = pd.concat(trades[name]), pd.concat(ports[name])
    row = {
        "variant": name,
        "trades": len(tr),
        "mean_hold": round(tr["hold"].mean(), 1),
        "net-mkt/trade%": round(tr["xs"].mean() * 100, 3),
        "daily%": ci_of(pv["ret"], 10)[0],
        "folds_beat_A": "-" if name == "A" else f"{fold_wins(pv)}/3",
        "exposure": round(pv["exposure"].mean(), 2),
    }
    if name != "A":
        txt, low = ci_of((pv["ret"] - pa["ret"]).to_numpy(), 10, CONF)
        row["variant-A daily% (99%)"] = txt
        verdicts[name] = (
            "INCONCLUSIVE"
            if len(tr) < 300
            else ("PASS" if low > 0 and fold_wins(pv) >= 2 else "FAIL")
        )
        row["verdict"] = verdicts[name]
    tbl.append(row)
out.append(pd.DataFrame(tbl).to_string(index=False))
out += ["", "## Per fold: compounded net portfolio return % (market = equal-weight average stock)", ""]
fr = []
for i, year in enumerate(FOLD_YEARS):
    r = {"year": year, "market%": round(((1 + ports["A"][i]["mkt"]).prod() - 1) * 100, 2)}
    for name in VARIANTS:
        r[name] = round(((1 + ports[name][i]["ret"]).prod() - 1) * 100, 2)
    fr.append(r)
out.append(pd.DataFrame(fr).to_string(index=False))
out += ["", "## Descriptive only: A's own trades, net-market % by filter state at entry (pooled; never a candidate filter)", ""]
ta = pd.concat(trades["A"])
dg = [
    {
        "filter": k,
        "true_n": int(ta[k].sum()),
        "true%": round(ta.loc[ta[k], "xs"].mean() * 100, 3),
        "false_n": int((~ta[k]).sum()),
        "false%": round(ta.loc[~ta[k], "xs"].mean() * 100, 3),
    }
    for k in MASKS
]
out.append(pd.DataFrame(dg).to_string(index=False))
out += ["", "## Verdicts (frozen rule; development evidence only): " + ", ".join(f"{k}={v}" for k, v in verdicts.items())]
text = "\n".join(out)
if a.out:
    open(a.out, "w").write(text + "\n")
print(text)
