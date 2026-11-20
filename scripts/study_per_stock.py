# ruff: noqa: E501
"""Study: can a model trained on ONE stock's own history (its price habits, its own filed fundamentals, and crowd-behaviour features) say when to buy and when to sell it?

Label (triple barrier, long side, tradeable): enter at the NEXT session's open; take-profit K x ATR14 above the entry, stop-loss K x ATR14 below, time limit H sessions.
  +1 take-profit hit first, -1 stop-loss hit first (both in one bar counts as the stop), 0 neither (exit at the close of session H).
Each stock gets its own 3-class gradient-boosting model (trained 2019 to 2022, judged only from 2024, a gap between). Output: P(+1) = buy confidence, P(-1) = stop-out/avoid confidence.
Feature groups, own stock only (nothing about other stocks or the market):
  T  technical habits: returns, volatility, RSI, MACD, distance from averages, volume and delivery against the stock's own norm.
  P  crowd behaviour: anchoring on the 52-week high/low, days since the high, nearness to round prices, gap size and streaks (over/under-reaction), drawdown from the recent high (loss aversion),
     the biggest recent daily jump (lottery chasing), volume spikes with the move (panic/euphoria), candle wicks (rejection).
  F  the stock's own filed fundamentals, known only the day after filing: growth, margins, returns on capital, debt, days since the last filing.
Controls: the same per-stock models with the training labels shuffled (what pure luck looks like), and ONE pooled model on all stocks (does a separate model per stock help at all?).
Judged by: AUC of P(+1) for "+1 happened" per stock and pooled; the top 5% most confident buys vs all rows (hit rate, mean trade return after a 0.5% round-trip cost); the same-day lift.
usage: study_per_stock.py [--db URL] [--n 150] [--k 1.5] [--horizon 10] [--seed 0]"""

import argparse
import json
import os
import sys
from bisect import bisect_left
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from study_common import BARS, flat_cost  # noqa: E402,I001

from algo.data import ratios as fr
from algo.screener.snapshot import quarters_since

DEV_END = json.loads(
    (Path(__file__).resolve().parent.parent / "config/research_holdout.json").read_text()
)["development_end"]  # a study never reads the protected holdout window
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--n", type=int, default=150, help="stocks sampled (0 = every liquid stock)")
ap.add_argument("--k", type=float, default=1.5, help="barrier distance in ATR14 units")
ap.add_argument("--horizon", type=int, default=10)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
H, K, COST = a.horizon, a.k, flat_cost()
TRAIN_END, TEST_START = np.datetime64("2022-12-31"), np.datetime64("2024-01-01")
FUND = [
    "revenue_growth",
    "profit_growth",
    "net_margin",
    "operating_margin",
    "roe",
    "roce",
    "debt_to_equity",
]

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-09-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= %s ORDER BY instrument_id, ts, dataset_version DESC",
        (DEV_END,),
    ).fetchall()
    splits: dict[int, list[date]] = {}
    for iid, ex in conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ):
        splits.setdefault(int(iid), []).append(ex)
bars = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v", "dq"])
del rows
bars["d"] = pd.to_datetime(bars["d"])

# --- pick the stocks: enough history, liquid -----------------------------------------------------------------------------------
turn = (bars["c"] * bars["v"] / 1e7).groupby(bars["iid"]).median()
n_bars = bars.groupby("iid").size()
ok_ids = sorted(
    int(i)
    for i in n_bars.index[(n_bars >= 1300) & (turn.reindex(n_bars.index) >= a.min_turnover_cr)]
)
rng = np.random.default_rng(a.seed)
ids = (
    sorted(rng.choice(ok_ids, size=a.n, replace=False).tolist())
    if 0 < a.n < len(ok_ids)
    else ok_ids
)
print(f"{len(ok_ids)} liquid stocks with 1300+ bars; using {len(ids)}")

with psycopg.connect(a.db) as conn:
    quarters = quarters_since(conn, date(2018, 1, 1), ids)


def fundamentals_daily(iid: int, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Each trading day: the ratios of the filings filed STRICTLY before that day (a one-day lag), forward-filled; plus days since the last filing."""
    qs = quarters.get((iid, "CONSOLIDATED")) or quarters.get((iid, "STANDALONE")) or []
    cols = [*FUND, "days_since_filing"]
    out = np.full((len(days), len(cols)), np.nan)
    snaps: list[tuple[date, list[float]]] = []
    for f in sorted({q.filed_at for q in qs}):
        known = fr.known_quarters(qs, f)
        if len(known) < 2:
            continue
        vals = fr.compute(known, None)
        snaps.append(
            (
                f.date(),
                [
                    float(vals[k].value) if k in vals and vals[k].value is not None else np.nan
                    for k in FUND
                ],
            )
        )
    fdays = [s[0] for s in snaps]
    for i, dd in enumerate(days):
        j = bisect_left(fdays, dd.date()) - 1  # last filing strictly before this day
        if j >= 0:
            out[i, : len(FUND)] = snaps[j][1]
            out[i, len(FUND)] = (dd.date() - fdays[j]).days
    return pd.DataFrame(out, index=days, columns=cols)


def stock_frame(iid: int, d: pd.DataFrame) -> pd.DataFrame | None:
    d = d.set_index("d").sort_index()
    o, h, lo, c, v, dq = (d[k].to_numpy(dtype="float64") for k in ("o", "h", "l", "c", "v", "dq"))
    n = len(d)
    if n < 400:
        return None
    ix = d.index
    cc, hh, ll, oo, vv = (pd.Series(x, ix) for x in (c, h, lo, o, v))
    ret1 = cc.pct_change()
    prev_c = cc.shift(1)
    tr = pd.concat([hh - ll, (hh - prev_c).abs(), (ll - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=14).mean()
    vol20 = ret1.rolling(20, min_periods=15).std()
    sma50, sma200 = cc.rolling(50, min_periods=50).mean(), cc.rolling(200, min_periods=200).mean()
    dl = cc.diff()
    rsi = 100 - 100 / (
        1
        + dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    )
    macd = cc.ewm(span=12, adjust=False).mean() - cc.ewm(span=26, adjust=False).mean()
    dpct = pd.Series(dq, ix) / vv.where(vv > 0) * 100
    hi252, lo252 = hh.rolling(252, min_periods=120).max(), ll.rolling(252, min_periods=120).min()
    hi20, lo20 = hh.rolling(20).max(), ll.rolling(20).min()
    days_hi = hh.rolling(252, min_periods=120).apply(
        lambda x: len(x) - 1 - int(np.argmax(x)), raw=True
    )
    step = 10.0 ** np.floor(
        np.log10(cc.clip(lower=1))
    )  # the nearest "round" price: multiples of 1/10th of the price's power of ten

    def near(unit: pd.Series) -> pd.Series:
        return (
            ((cc / unit) - (cc / unit).round()).abs() * unit / cc
        )  # share of the price away from the nearest multiple of `unit`

    gap = (oo - prev_c) / atr
    up = (ret1 > 0).astype(int) - (ret1 < 0).astype(int)
    streak = up * (up.groupby((up != up.shift()).cumsum()).cumcount() + 1)
    rg = (hh - ll).replace(0, np.nan)
    vr = vv / vv.rolling(20, min_periods=15).mean()
    feat = pd.DataFrame(
        {
            # T
            "r1": ret1,
            "r5": cc / cc.shift(5) - 1,
            "r20": cc / cc.shift(20) - 1,
            "r60": cc / cc.shift(60) - 1,
            "vol20": vol20,
            "atr_pct": atr / cc,
            "rsi": rsi,
            "macd": macd / cc,
            "d_sma50": cc / sma50 - 1,
            "d_sma200": cc / sma200 - 1,
            "vol_ratio": vr,
            "dpct": dpct,
            "dpct_ratio": dpct / dpct.rolling(20, min_periods=15).mean(),
            "close_pos": (cc - ll) / rg,
            # P
            "d_hi52": cc / hi252 - 1,
            "d_lo52": cc / lo252 - 1,
            "days_since_hi52": days_hi,
            "round_dist": near(step),
            "round_dist50": near(step / 2),
            "gap_atr": gap,
            "streak": streak,
            "dd_hi20_atr": (cc - hi20) / atr,
            "rally_lo20_atr": (cc - lo20) / atr,
            "max_jump20": ret1.rolling(20, min_periods=15).max(),
            "min_drop20": ret1.rolling(20, min_periods=15).min(),
            "spike_signed": vr * np.sign(ret1),
            "ret_z": ret1 / vol20.shift(1),
            "upper_wick": (hh - np.maximum(oo, cc)) / rg,
            "lower_wick": (np.minimum(oo, cc) - ll) / rg,
        },
        index=ix,
    ).join(fundamentals_daily(iid, ix))
    # triple barrier: enter at the next open; barriers K x ATR (known at the signal day) around it
    ent = np.roll(o, -1)
    a_ = atr.to_numpy()
    tp, sl = ent + K * a_, ent - K * a_
    lab = np.zeros(n, dtype=np.int8)
    ret = np.full(n, np.nan)
    undecided = np.ones(n, dtype=bool)
    for j in range(1, H + 1):  # session t+j (j=1 is the entry session itself: its range counts)
        hj, lj, oj = np.roll(h, -j), np.roll(lo, -j), np.roll(o, -j)
        hit_sl = undecided & (lj <= sl)
        hit_tp = undecided & (hj >= tp) & ~hit_sl  # both in one bar: the stop
        ret[hit_sl] = (
            np.minimum(oj[hit_sl], sl[hit_sl]) / ent[hit_sl] - 1
            if j > 1
            else sl[hit_sl] / ent[hit_sl] - 1
        )  # a gap through the stop fills at the open
        ret[hit_tp] = tp[hit_tp] / ent[hit_tp] - 1
        lab[hit_sl], lab[hit_tp] = -1, 1
        undecided &= ~(hit_sl | hit_tp)
    cH = np.roll(c, -H)
    ret[undecided] = cH[undecided] / ent[undecided] - 1
    hold = cH / ent - 1  # plain buy-and-hold over the same window, to see the stock's own drift
    valid = np.arange(n) < n - H - 1
    # drop rows whose look-back or look-ahead crosses a split/bonus (the bars are raw prices)
    dates = ix.to_numpy()
    bad = np.zeros(n, dtype=bool)
    for ex in splits.get(iid, []):
        e = np.datetime64(ex)
        bad |= (dates >= e - np.timedelta64(15, "D")) & (dates <= e + np.timedelta64(365, "D"))
    feat["y"], feat["ret"], feat["hold"] = lab, ret, hold
    feat["ok"] = valid & ~bad & np.isfinite(a_) & (a_ > 0) & np.isfinite(ent)
    feat["iid"] = iid
    return feat


frames = []
for iid in ids:
    f = stock_frame(iid, bars[bars["iid"] == iid][["d", "o", "h", "l", "c", "v", "dq"]])
    if f is not None:
        frames.append(f)
del bars
allf = pd.concat(frames)
allf.index.name = "d"
allf = allf[allf["ok"]].reset_index()
dts = allf["d"].to_numpy()
T = [
    "r1",
    "r5",
    "r20",
    "r60",
    "vol20",
    "atr_pct",
    "rsi",
    "macd",
    "d_sma50",
    "d_sma200",
    "vol_ratio",
    "dpct",
    "dpct_ratio",
    "close_pos",
]
P = [
    "d_hi52",
    "d_lo52",
    "days_since_hi52",
    "round_dist",
    "round_dist50",
    "gap_atr",
    "streak",
    "dd_hi20_atr",
    "rally_lo20_atr",
    "max_jump20",
    "min_drop20",
    "spike_signed",
    "ret_z",
    "upper_wick",
    "lower_wick",
]
F = [*FUND, "days_since_filing"]
tr_all = dts <= TRAIN_END - np.timedelta64(2 * H, "D")
te_all = dts >= TEST_START
print(f"{len(allf):,} usable stock-days; train {tr_all.sum():,}, judged {te_all.sum():,}")
y_all = allf["y"].to_numpy()
ret_all = allf["ret"].to_numpy()
iid_all = allf["iid"].to_numpy()
print(
    f"label mix, judged rows: +1 {100 * (y_all[te_all] == 1).mean():.1f}%  -1 {100 * (y_all[te_all] == -1).mean():.1f}%  time-out {100 * (y_all[te_all] == 0).mean():.1f}%;  mean barrier trade {100 * np.nanmean(ret_all[te_all]):+.3f}% vs plain {H}-session hold {100 * np.nanmean(allf['hold'].to_numpy()[te_all]):+.3f}% (before cost)\n"
)


def model() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=80,
        learning_rate=0.05,
        max_depth=3,
        min_samples_leaf=30,
        l2_regularization=5.0,
        random_state=0,
    )


def proba(m: HistGradientBoostingClassifier, X: np.ndarray, cls: int) -> np.ndarray:
    cl = list(m.classes_)
    return m.predict_proba(X)[:, cl.index(cls)] if cls in cl else np.zeros(len(X))


def run(name: str, cols: list[str], mode: str) -> None:
    """mode: 'own' (one model per stock) | 'shuffle' (per stock, training labels shuffled) | 'pooled' (one model for everyone)."""
    X = allf[cols].to_numpy(dtype="float32", copy=True)
    X[~np.isfinite(X)] = np.nan
    pb, ps = np.full(len(allf), np.nan), np.full(len(allf), np.nan)  # P(+1) and P(-1)
    r = np.random.default_rng(1)
    if mode == "pooled":
        tri = np.nonzero(tr_all)[0]
        tri = tri[:: max(1, len(tri) // 400_000)]
        m = (
            model()
            .set_params(max_iter=200, max_depth=4, min_samples_leaf=500)
            .fit(X[tri], y_all[tri])
        )
        tei = np.nonzero(te_all)[0]
        pb[tei], ps[tei] = proba(m, X[tei], 1), proba(m, X[tei], -1)
    else:
        for i in np.unique(iid_all):
            msk = iid_all == i
            tri, tei = np.nonzero(msk & tr_all)[0], np.nonzero(msk & te_all)[0]
            if len(tri) < 500 or len(tei) < 200:
                continue
            yy = y_all[tri].copy()
            if mode == "shuffle":
                r.shuffle(yy)
            if len(set(yy)) < 2:
                continue
            live = ~np.isnan(
                X[tri]
            ).all(
                axis=0
            )  # a fundamentals column with no filing yet in the training years has nothing to learn from
            m = model().fit(X[tri][:, live], yy)
            pb[tei], ps[tei] = proba(m, X[tei][:, live], 1), proba(m, X[tei][:, live], -1)
    sel = ~np.isnan(pb)
    y, ret, d, i_, pbs, pss = y_all[sel], ret_all[sel], dts[sel], iid_all[sel], pb[sel], ps[sel]
    aucs_b, aucs_s = (
        [],
        [],
    )  # per-stock AUC of P(+1) for "+1 happened" and of P(-1) for "-1 happened"
    for i in np.unique(i_):
        m_ = i_ == i
        if 0 < (y[m_] == 1).sum() < m_.sum():
            aucs_b.append(roc_auc_score(y[m_] == 1, pbs[m_]))
        if 0 < (y[m_] == -1).sum() < m_.sum():
            aucs_s.append(roc_auc_score(y[m_] == -1, pss[m_]))
    ab, as_ = np.array(aucs_b), np.array(aucs_s)
    print(f"[{name}]  {len(np.unique(i_))} stocks, {sel.sum():,} rows")
    print(
        f"   AUC buy side (P+1 vs +1):  pooled {roc_auc_score(y == 1, pbs):.4f}; per stock mean {ab.mean():.4f}, {100 * (ab > 0.55).mean():.0f}% of stocks above 0.55, {100 * (ab < 0.45).mean():.0f}% below 0.45"
    )
    print(
        f"   AUC sell side (P-1 vs -1): pooled {roc_auc_score(y == -1, pss):.4f}; per stock mean {as_.mean():.4f}, {100 * (as_ > 0.55).mean():.0f}% above 0.55, {100 * (as_ < 0.45).mean():.0f}% below 0.45"
    )
    base_b = pd.Series((y == 1).astype(float)).groupby(d).transform("mean").to_numpy()
    base_s = pd.Series((y == -1).astype(float)).groupby(d).transform("mean").to_numpy()
    print(
        f"   all rows: +1 {100 * (y == 1).mean():.1f}%, -1 {100 * (y == -1).mean():.1f}%, mean trade net {100 * (np.nanmean(ret) - COST):+.3f}%"
    )
    ob, os_ = np.argsort(-pbs), np.argsort(-pss)
    for c in (0.01, 0.05, 0.20):
        k = max(1, int(c * sel.sum()))
        t, s_ = ob[:k], os_[:k]
        print(
            f"   top {100 * c:>3.0f}% BUY conf: +1 {100 * (y[t] == 1).mean():5.1f}% (same-day lift {100 * ((y[t] == 1) - base_b[t]).mean():+5.1f}pt, {len(np.unique(d[t]))} days), -1 {100 * (y[t] == -1).mean():5.1f}%, trade net {100 * (np.nanmean(ret[t]) - COST):+.3f}%"
            f"  |  top SELL conf: -1 {100 * (y[s_] == -1).mean():5.1f}% (lift {100 * ((y[s_] == -1) - base_s[s_]).mean():+5.1f}pt), +1 {100 * (y[s_] == 1).mean():5.1f}%, trade net {100 * (np.nanmean(ret[s_]) - COST):+.3f}%"
        )
    print()


run("per-stock, T (technical habits)", T, "own")
run("per-stock, T+P (plus crowd behaviour)", T + P, "own")
run("per-stock, T+P+F (plus own fundamentals)", T + P + F, "own")
run("per-stock, T+P+F, TRAINING LABELS SHUFFLED (luck control)", T + P + F, "shuffle")
run("ONE pooled model, T+P+F (control: does per-stock help?)", T + P + F, "pooled")
