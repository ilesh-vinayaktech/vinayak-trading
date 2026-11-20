# ruff: noqa: E501
"""Study: first decide the market and sector regime (bullish / bearish / sideways), then, given the regime and the stock's own price action, can ONE model say BUY / SELL / HOLD with a confidence we can trust?

Step 1, regime by a plain rule on a close series (Nifty 500; each sector's own equal-weight index built from its Nifty 500 members; the stock itself):
  bullish  = close > 200-day average, 50-day above 200-day, and the 50-day average rising over 20 sessions;  bearish = the mirror;  sideways = anything else.
Step 2, triple-barrier labels (enter at the next open, +/-K x ATR14, H sessions): BUY = upper barrier first, SELL = lower barrier first (a long would be stopped out: in cash that means sell/avoid),
  HOLD = neither (or both inside one bar). One 3-class gradient-boosting model over the stock's own price-action features + the regimes + index/sector trend features.
  Probabilities are calibrated (isotonic, fitted on a year the model did not train on or get judged on), so "60%" should mean about 60%.
Judged from 2024 on. Reports: ablation (stock-only / +index regime / +sector), the reliability table (stated confidence vs what happened), then the BUY/SELL calls at each confidence cut: how many, how often right,
same-day lift (does it pick better than the day's average stock), the trade after a 0.5% round trip, and the result inside each index regime.
usage: study_regime_signal.py [--db URL] [--k 1.5] [--horizon 10]"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
from study_common import BARS, flat_cost  # noqa: E402,I001

DEV_END = json.loads(
    (Path(__file__).resolve().parent.parent / "config/research_holdout.json").read_text()
)["development_end"]  # a study never reads the protected holdout window

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--k", type=float, default=1.5)
ap.add_argument("--horizon", type=int, default=10)
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
H, K, COST = a.horizon, a.k, flat_cost()
GAP = np.timedelta64(2 * H, "D")
CAL_START, CAL_END = np.datetime64("2022-07-01"), np.datetime64("2023-12-31")
TEST_START = np.datetime64("2024-01-01")

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-01-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= %s ORDER BY instrument_id, ts, dataset_version DESC",
        (DEV_END,),
    ).fetchall()
    splits: dict[int, list[date]] = {}
    for iid, ex in conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ):
        splits.setdefault(int(iid), []).append(ex)
    sector_of = {
        int(i): s
        for i, s in conn.execute(
            "SELECT DISTINCT ON (instrument_id) instrument_id, sector FROM instrument_sector ORDER BY instrument_id, effective_from DESC"
        )
    }
    idx = pd.DataFrame(
        conn.execute(
            "SELECT trade_date, close::float8 FROM index_bar_1d WHERE exchange='NSE' AND symbol='NIFTY 500' AND trade_date >= '2018-01-01' ORDER BY trade_date"
        ).fetchall(),
        columns=["d", "c"],
    )
bars = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v", "dq"])
del rows
bars["d"] = pd.to_datetime(bars["d"])
idx["d"] = pd.to_datetime(idx["d"])
bars = bars[bars["iid"].isin(sector_of)]  # sectors exist only for the Nifty 500 list


def regime(c: pd.Series) -> pd.Series:
    """+1 bullish, -1 bearish, 0 sideways (see the module note)."""
    s50, s200 = c.rolling(50, min_periods=50).mean(), c.rolling(200, min_periods=200).mean()
    slope = s50 / s50.shift(20) - 1
    out = pd.Series(0.0, index=c.index)
    out[(c > s200) & (s50 > s200) & (slope > 0)] = 1
    out[(c < s200) & (s50 < s200) & (slope < 0)] = -1
    out[s200.isna()] = np.nan
    return out


def trend_block(c: pd.Series, p: str) -> pd.DataFrame:
    r1 = c.pct_change()
    return pd.DataFrame(
        {
            f"{p}_regime": regime(c),
            f"{p}_r20": c / c.shift(20) - 1,
            f"{p}_r60": c / c.shift(60) - 1,
            f"{p}_vol20": r1.rolling(20, min_periods=15).std(),
            f"{p}_dd": c / c.rolling(252, min_periods=120).max() - 1,
        }
    )


# market and sector indexes (a signal at day t uses only closes up to t)
mkt = trend_block(idx.set_index("d")["c"], "idx")
daily_ret = bars.assign(r=bars.groupby("iid")["c"].pct_change()).pivot(
    index="d", columns="iid", values="r"
)
daily_ret = daily_ret.where(daily_ret.abs() < 0.5)  # a split/bonus day is not a return
sec_blocks = {}
for sec in sorted(set(sector_of.values())):
    members = [i for i, s in sector_of.items() if s == sec and i in daily_ret.columns]
    if len(members) >= 3:
        sec_blocks[sec] = trend_block(
            (1 + daily_ret[members].mean(axis=1).fillna(0)).cumprod(), "sec"
        )
print(
    f"{len(sec_blocks)} sector indexes built; Nifty 500 regime share since 2020: "
    + ", ".join(
        f"{n} {100 * (mkt['idx_regime'].loc['2020':] == v).mean():.0f}%"
        for n, v in (("bull", 1), ("side", 0), ("bear", -1))
    )
)

turn = (bars["c"] * bars["v"] / 1e7).groupby(bars["iid"]).median()
nb = bars.groupby("iid").size()
ids = sorted(int(i) for i in nb.index[(nb >= 1000) & (turn.reindex(nb.index) >= a.min_turnover_cr)])
print(f"{len(ids)} liquid sector-mapped stocks")


def stock_frame(iid: int, d: pd.DataFrame) -> pd.DataFrame | None:
    d = d.set_index("d").sort_index()
    ix = d.index
    o, h, lo, c = (d[k].to_numpy(dtype="float64") for k in ("o", "h", "l", "c"))
    n = len(d)
    cc, hh, ll, oo, vv = (pd.Series(x, ix) for x in (c, h, lo, o, d["v"].to_numpy(dtype="float64")))
    ret1 = cc.pct_change()
    prev_c = cc.shift(1)
    atr = (
        pd.concat([hh - ll, (hh - prev_c).abs(), (ll - prev_c).abs()], axis=1)
        .max(axis=1)
        .rolling(14, min_periods=14)
        .mean()
    )
    vol20 = ret1.rolling(20, min_periods=15).std()
    sma50, sma200 = cc.rolling(50, min_periods=50).mean(), cc.rolling(200, min_periods=200).mean()
    dl = cc.diff()
    rsi = 100 - 100 / (
        1
        + dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    )
    dpct = pd.Series(d["dq"].to_numpy(dtype="float64"), ix) / vv.where(vv > 0) * 100
    hi252, lo252 = hh.rolling(252, min_periods=120).max(), ll.rolling(252, min_periods=120).min()
    hi20, lo20 = hh.rolling(20).max(), ll.rolling(20).min()
    step = 10.0 ** np.floor(np.log10(cc.clip(lower=1)))
    up = (ret1 > 0).astype(int) - (ret1 < 0).astype(int)
    rg = (hh - ll).replace(0, np.nan)
    vr = vv / vv.rolling(20, min_periods=15).mean()
    r20, r60 = cc / cc.shift(20) - 1, cc / cc.shift(60) - 1
    sec = sec_blocks.get(sector_of[iid])
    if sec is None:
        return None
    f = pd.DataFrame(
        {
            "r1": ret1,
            "r5": cc / cc.shift(5) - 1,
            "r20": r20,
            "r60": r60,
            "vol20": vol20,
            "atr_pct": atr / cc,
            "rsi": rsi,
            "d_sma50": cc / sma50 - 1,
            "d_sma200": cc / sma200 - 1,
            "vol_ratio": vr,
            "dpct_ratio": dpct / dpct.rolling(20, min_periods=15).mean(),
            "close_pos": (cc - ll) / rg,
            "d_hi52": cc / hi252 - 1,
            "d_lo52": cc / lo252 - 1,
            "round_dist": ((cc / step) - (cc / step).round()).abs() * step / cc,
            "gap_atr": (oo - prev_c) / atr,
            "streak": up * (up.groupby((up != up.shift()).cumsum()).cumcount() + 1),
            "dd_hi20_atr": (cc - hi20) / atr,
            "rally_lo20_atr": (cc - lo20) / atr,
            "max_jump20": ret1.rolling(20, min_periods=15).max(),
            "spike_signed": vr * np.sign(ret1),
            "upper_wick": (hh - np.maximum(oo, cc)) / rg,
            "lower_wick": (np.minimum(oo, cc) - ll) / rg,
            "own_regime": regime(cc),
        },
        index=ix,
    )
    f = f.join(mkt).join(sec)
    f["rel_idx20"], f["rel_idx60"] = r20 - f["idx_r20"], r60 - f["idx_r60"]
    f["rel_sec20"], f["rel_sec60"] = r20 - f["sec_r20"], r60 - f["sec_r60"]
    f["sec_vs_idx20"] = f["sec_r20"] - f["idx_r20"]
    # triple barrier from the next open
    ent = np.roll(o, -1)
    a_ = atr.to_numpy()
    tp, sl = ent + K * a_, ent - K * a_
    lab = np.zeros(n, dtype=np.int8)
    ret = np.full(n, np.nan)
    undecided = np.ones(n, dtype=bool)
    for j in range(1, H + 1):
        hj, lj, oj = np.roll(h, -j), np.roll(lo, -j), np.roll(o, -j)
        hit_sl = undecided & (lj <= sl)
        hit_tp = undecided & (hj >= tp) & ~hit_sl
        ret[hit_sl] = (np.minimum(oj[hit_sl], sl[hit_sl]) if j > 1 else sl[hit_sl]) / ent[
            hit_sl
        ] - 1
        ret[hit_tp] = tp[hit_tp] / ent[hit_tp] - 1
        lab[hit_sl], lab[hit_tp] = -1, 1
        undecided &= ~(hit_sl | hit_tp)
    ret[undecided] = np.roll(c, -H)[undecided] / ent[undecided] - 1
    dates = ix.to_numpy()
    bad = np.zeros(n, dtype=bool)
    for ex in splits.get(iid, []):
        e = np.datetime64(ex)
        bad |= (dates >= e - np.timedelta64(15, "D")) & (dates <= e + np.timedelta64(365, "D"))
    f["y"], f["ret"], f["iid"] = lab, ret, iid
    f["ok"] = (
        (np.arange(n) < n - H - 1)
        & ~bad
        & np.isfinite(a_)
        & (a_ > 0)
        & np.isfinite(ent)
        & (dates >= np.datetime64("2019-10-01"))
    )
    return f


frames = [
    f
    for iid in ids
    if (f := stock_frame(iid, bars[bars["iid"] == iid][["d", "o", "h", "l", "c", "v", "dq"]]))
    is not None
]
del bars
allf = pd.concat(frames)
allf.index.name = "d"
allf = allf[allf["ok"] & allf["idx_regime"].notna() & allf["sec_regime"].notna()].reset_index()
dts = allf["d"].to_numpy()
y_all, ret_all = allf["y"].to_numpy(), allf["ret"].to_numpy()
STOCK = [
    c
    for c in allf.columns
    if c not in {"d", "y", "ret", "iid", "ok"}
    and not c.startswith(("idx_", "sec_", "rel_", "own_regime"))
]
IDX = ["idx_regime", "idx_r20", "idx_r60", "idx_vol20", "idx_dd", "rel_idx20", "rel_idx60"]
SEC = [
    "sec_regime",
    "sec_r20",
    "sec_r60",
    "sec_vol20",
    "sec_dd",
    "rel_sec20",
    "rel_sec60",
    "sec_vs_idx20",
]
OWN = ["own_regime"]
tr = dts < CAL_START - GAP
ca = (dts >= CAL_START) & (dts <= CAL_END - GAP)
te = dts >= TEST_START
print(f"{len(allf):,} stock-days; train {tr.sum():,}, calibrate {ca.sum():,}, judged {te.sum():,}")
print(
    f"judged label mix: BUY {100 * (y_all[te] == 1).mean():.1f}%  SELL {100 * (y_all[te] == -1).mean():.1f}%  HOLD {100 * (y_all[te] == 0).mean():.1f}%"
)
reg_te = allf["idx_regime"].to_numpy()[te]
print(
    "base rates by index regime (judged): "
    + "; ".join(
        f"{n}: BUY {100 * (y_all[te][reg_te == v] == 1).mean():.1f}% SELL {100 * (y_all[te][reg_te == v] == -1).mean():.1f}% ({(reg_te == v).sum():,} rows)"
        for n, v in (("bull", 1), ("sideways", 0), ("bear", -1))
    )
    + "\n"
)


def fit_predict(cols: list[str], calibrate: bool) -> np.ndarray:
    """Probabilities [SELL, HOLD, BUY] on the judged rows."""
    X = allf[cols].to_numpy(dtype="float32", copy=True)
    X[~np.isfinite(X)] = np.nan
    tri = np.nonzero(tr)[0]
    tri = tri[:: max(1, len(tri) // 500_000)]
    m = HistGradientBoostingClassifier(
        max_iter=250,
        learning_rate=0.04,
        max_depth=4,
        min_samples_leaf=400,
        l2_regularization=5.0,
        random_state=0,
    ).fit(X[tri], y_all[tri])
    p_te = m.predict_proba(X[te])
    if not calibrate:
        return p_te
    p_ca = m.predict_proba(X[ca])
    out = p_te.copy()
    for k, cls in enumerate(m.classes_):  # one isotonic map per class, then renormalise
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(
            p_ca[:, k], (y_all[ca] == cls).astype(float)
        )
        out[:, k] = iso.predict(p_te[:, k])
    return out / out.sum(axis=1, keepdims=True)


yt, rt, dt, it = y_all[te], ret_all[te], dts[te], allf["iid"].to_numpy()[te]
for name, cols in (
    ("stock price action only", STOCK),
    ("+ index regime/trend", STOCK + IDX + OWN),
    ("+ sector regime/trend (full)", STOCK + IDX + OWN + SEC),
):
    p = fit_predict(cols, calibrate=False)
    print(
        f"[{name}]  AUC BUY {roc_auc_score(yt == 1, p[:, 2]):.4f}   AUC SELL {roc_auc_score(yt == -1, p[:, 0]):.4f}"
    )
print()

p = fit_predict(STOCK + IDX + OWN + SEC, calibrate=True)
pb, ps = p[:, 2], p[:, 0]
print("=== reliability (calibrated, full model): stated confidence vs what happened")
for nm, pr, hit in (("BUY ", pb, yt == 1), ("SELL", ps, yt == -1)):
    qs = np.unique(np.quantile(pr, [0, 0.5, 0.8, 0.9, 0.95, 0.99, 0.999, 1]))
    for lo_, hi_ in zip(qs[:-1], qs[1:], strict=False):
        m_ = (pr >= lo_) & (pr <= hi_)
        print(
            f"   {nm} stated {100 * lo_:5.1f}-{100 * hi_:5.1f}%: mean stated {100 * pr[m_].mean():5.1f}%, happened {100 * hit[m_].mean():5.1f}%  (n={m_.sum():,})"
        )
print(
    "\n=== the calls: BUY if P(BUY) >= cut and above P(SELL); SELL if P(SELL) >= cut and above P(BUY); else HOLD"
)
base_b = pd.Series((yt == 1).astype(float)).groupby(dt).transform("mean").to_numpy()
base_s = pd.Series((yt == -1).astype(float)).groupby(dt).transform("mean").to_numpy()
for cut in (0.40, 0.45, 0.50, 0.55, 0.60):
    buy, sell = (pb >= cut) & (pb > ps), (ps >= cut) & (ps > pb)
    line = f"cut {100 * cut:.0f}%: "
    if buy.sum():
        line += f"BUY n={buy.sum():,} ({len(np.unique(dt[buy]))} days) right {100 * (yt[buy] == 1).mean():.1f}% (lift {100 * ((yt[buy] == 1) - base_b[buy]).mean():+.1f}pt), trade net {100 * (np.nanmean(rt[buy]) - COST):+.2f}%"
    if sell.sum():
        line += f" | SELL n={sell.sum():,} ({len(np.unique(dt[sell]))} days) right {100 * (yt[sell] == -1).mean():.1f}% (lift {100 * ((yt[sell] == -1) - base_s[sell]).mean():+.1f}pt), a long taken there returned {100 * np.nanmean(rt[sell]):+.2f}%"
    print("  ", line)
print("\n=== by index regime (cut 45%)")
for nm, v in (("bullish", 1), ("sideways", 0), ("bearish", -1)):
    r_ = reg_te == v
    buy, sell = (pb >= 0.45) & (pb > ps) & r_, (ps >= 0.45) & (ps > pb) & r_
    print(
        f"   {nm:<9} rows {r_.sum():>7,}: BUY n={buy.sum():>5,} right {100 * (yt[buy] == 1).mean() if buy.sum() else float('nan'):5.1f}% (this regime's base {100 * (yt[r_] == 1).mean():.1f}%)  |  SELL n={sell.sum():>5,} right {100 * (yt[sell] == -1).mean() if sell.sum() else float('nan'):5.1f}% (base {100 * (yt[r_] == -1).mean():.1f}%)"
    )
print("\n=== by year (cut 45%)")
yrs = pd.Series(dt).dt.year.to_numpy()
for yr in sorted(set(yrs)):
    r_ = yrs == yr
    buy, sell = (pb >= 0.45) & (pb > ps) & r_, (ps >= 0.45) & (ps > pb) & r_
    print(
        f"   {yr}: BUY n={buy.sum():>5,} right {100 * (yt[buy] == 1).mean() if buy.sum() else float('nan'):5.1f}% (base {100 * (yt[r_] == 1).mean():.1f}%) | SELL n={sell.sum():>5,} right {100 * (yt[sell] == -1).mean() if sell.sum() else float('nan'):5.1f}% (base {100 * (yt[r_] == -1).mean():.1f}%)"
    )

print(
    "\n=== the calls by RANK instead of stated confidence (the stated numbers drift between years, the ordering may not)"
)
for label, cols in (
    ("stock price action only", STOCK),
    ("full: + index/sector regime", STOCK + IDX + OWN + SEC),
):
    q = fit_predict(cols, calibrate=False)
    qb, qs_ = q[:, 2], q[:, 0]
    print(f"[{label}]")
    for nm, sc, hit, base in (("BUY ", qb, yt == 1, base_b), ("SELL", qs_, yt == -1, base_s)):
        order = np.argsort(-sc)
        for c in (0.001, 0.01, 0.05, 0.20):
            t = order[: max(1, int(c * len(sc)))]
            yrs_t = pd.Series(dt[t]).dt.year.to_numpy()
            by_year = " ".join(
                f"{yy}:{100 * hit[t][yrs_t == yy].mean():.0f}%" for yy in sorted(set(yrs_t))
            )
            extra = (
                f"a long there returned {100 * np.nanmean(rt[t]):+.2f}%"
                if nm == "SELL"
                else f"trade net {100 * (np.nanmean(rt[t]) - COST):+.2f}%"
            )
            print(
                f"   top {100 * c:5.1f}% {nm}: n={len(t):>6,} on {len(np.unique(dt[t])):>3} days, right {100 * hit[t].mean():5.1f}% (day base {100 * base[t].mean():.1f}%, lift {100 * (hit[t] - base[t]).mean():+5.1f}pt; by year {by_year}), {extra}"
            )
