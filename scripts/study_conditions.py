# ruff: noqa: E501
"""Fresh Early Signs study (2026-11-19): what market conditions make a price behaviour more likely to pay? Daily bars, every liquid NSE stock since 2019.

Follows the research direction in order, with no reuse of earlier conclusions:
  1 each feature ALONE   (trend, momentum, volatility, volume, price structure, market context): mean / median / % up / best-case (MFE) / worst-case (MAE) / n at 5, 10, 20 sessions
  2 each feature by MARKET REGIME (Nifty 50 up / down / sideways, high / low volatility)
  3 stacked combinations: RSI>60 -> + trending market -> + relative volume -> + breaks the 20-day high
  4 FAILED vs WORKED breakouts: how their features differ
  5 OPPORTUNITY vs DIRECTION: does a feature raise the odds of a big move, separately from which way?
Every test is counted (the Bonferroni bar rises with the count). Periods: DEV 2019-2022 (look here), VAL 2023 (confirm), HOLD 2024+ (touched only with --final, and then only the
survivors frozen from DEV+VAL). All features are known at the bar's close; entry is that close. Return is close(+h)/close - 1; "edge" is that less the median stock that day.
Costs: --cost-pct (default 0.25) is charged once per round trip against the raw return ("net"). Overlapping horizons: t uses every h-th day. Splits/bonuses are dropped.
usage: study_conditions.py [--db URL] [--final] [--log tests.csv]"""

import argparse
import math
import os
import sys
from statistics import NormalDist

import numpy as np
import pandas as pd
import psycopg

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
ap.add_argument("--cost-pct", type=float, default=0.25)
ap.add_argument(
    "--final", action="store_true", help="evaluate the frozen survivors once on the 2024+ holdout"
)
ap.add_argument("--log", help="write every hypothesis tested to this CSV")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
HZS = (5, 10, 20)
VAL0, HOLD0 = np.datetime64("2023-01-01"), np.datetime64("2024-01-01")

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, high::float8, low::float8, close::float8, volume::float8"
        " FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= '2019-01-01' ORDER BY instrument_id, ts, dataset_version DESC"
    ).fetchall()
    splits = conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ).fetchall()
    nifty = conn.execute(
        "SELECT trade_date, close::float8 FROM index_bar_1d WHERE symbol='NIFTY 50' AND trade_date >= '2018-06-01' ORDER BY trade_date"
    ).fetchall()
    sect = conn.execute(
        "SELECT DISTINCT ON (instrument_id) instrument_id, sector FROM instrument_sector ORDER BY instrument_id, effective_from DESC"
    ).fetchall()

df = pd.DataFrame(rows, columns=["iid", "d", "h", "l", "c", "v"])
del rows
df["d"] = pd.to_datetime(df["d"])
H, L, C, V = (
    df.pivot(index="d", columns="iid", values=k).sort_index() for k in ("h", "l", "c", "v")
)
del df
T, S = C.shape
idx = C.index.values
NF = pd.Series({pd.Timestamp(d): c for d, c in nifty}).reindex(C.index, method="ffill")

# ---------------------------------------------------------------- features (all causal)
ema = lambda x, n: x.ewm(span=n, adjust=False, min_periods=n).mean()  # noqa: E731
sma = lambda x, n: x.rolling(n, min_periods=n).mean()  # noqa: E731
pc = C.shift(1)
tr = np.maximum(H - L, np.maximum((H - pc).abs(), (L - pc).abs()))
atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
e20, e50 = ema(C, 20), ema(C, 50)
dl = C.diff()
rsi = 100 - 100 / (
    1
    + dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
)
macd = ema(C, 12) - ema(C, 26)
hist = macd - macd.ewm(span=9, adjust=False).mean()
up, dn = H.diff().clip(lower=0), (-L.diff()).clip(lower=0)
pdm, mdm = up.where(up > dn, 0.0), dn.where(dn > up, 0.0)
pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / atr
mdi = 100 * mdm.ewm(alpha=1 / 14, adjust=False).mean() / atr
adx = (100 * (pdi - mdi).abs() / (pdi + mdi)).ewm(alpha=1 / 14, adjust=False).mean()
sd20 = C.rolling(20, min_periods=20).std()
bwid = 4 * sd20 / sma(C, 20)
bw_lo = bwid.rolling(120, min_periods=60).quantile(0.2)
vavg = V.shift(1).rolling(20, min_periods=15).mean()
hi20, lo20 = (
    H.shift(1).rolling(20, min_periods=20).max(),
    L.shift(1).rolling(20, min_periods=20).min(),
)
hi52 = H.shift(1).rolling(252, min_periods=200).max()
brk20 = C > hi20
# bars in a row whose prior-20-bar range stayed under 12% of price: how long the stock has been consolidating
tight_np = (((hi20 - lo20) / C) < 0.12).to_numpy()
cv = np.zeros((T, S))
for t in range(1, T):
    cv[t] = np.where(tight_np[t], cv[t - 1] + 1, 0)
cons = pd.DataFrame(cv, index=C.index, columns=C.columns)
lvl = hi20.where(brk20).ffill(limit=10)  # the level broken in the last 10 bars
nearhi = (
    (H.shift(1) >= 0.99 * hi20).astype(float).rolling(40, min_periods=20).sum()
)  # earlier attempts at the level
ret20, ret60 = C / C.shift(20) - 1, C / C.shift(60) - 1
sec = pd.Series(dict(sect)).reindex(C.columns)
secret = ret20.T.groupby(sec.values).transform("mean").T
nret = NF / NF.shift(60) - 1
nsma50, nsma200 = NF.rolling(50, min_periods=50).mean(), NF.rolling(200, min_periods=200).mean()
mk_up = ((NF > nsma50) & (nsma50 > nsma50.shift(10)) & (nsma50 > nsma200)).fillna(False)
mk_dn = ((NF < nsma50) & (nsma50 < nsma50.shift(10))).fillna(False)
mk_side = ~mk_up & ~mk_dn
nrv = NF.pct_change().rolling(20, min_periods=20).std()
mk_hv = (nrv > nrv.rolling(250, min_periods=120).median()).fillna(False)
breadth = (C > sma(C, 50)).where(C.notna()).mean(axis=1)


def row2d(s: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        np.broadcast_to(s.to_numpy()[:, None], (T, S)), index=C.index, columns=C.columns
    )


F: dict[str, tuple[str, pd.DataFrame]] = {
    # trend
    "ema20>ema50": ("trend", e20 > e50),
    "ema20 rising (5d > +1%)": ("trend", (e20 / e20.shift(5) - 1) > 0.01),
    "ADX>25 (strong trend)": ("trend", adx > 25),
    "ADX<15 (no trend)": ("trend", adx < 15),
    # momentum
    "RSI>60": ("momentum", rsi > 60),
    "RSI<40": ("momentum", rsi < 40),
    "MACD hist>0 and rising": ("momentum", (hist > 0) & (hist > hist.shift(1))),
    "ROC10>5%": ("momentum", (C / C.shift(10) - 1) > 0.05),
    # volatility
    "ATR5/ATR20>1.3 (expanding)": (
        "volatility",
        tr.rolling(5).mean() / tr.rolling(20).mean() > 1.3,
    ),
    "BB width in own bottom 20% (squeeze)": ("volatility", bwid < bw_lo),
    "squeeze then expansion": (
        "volatility",
        (bwid.shift(1) < bw_lo.shift(1)) & (tr > 1.5 * atr.shift(1)),
    ),
    # volume
    "rel volume>=1.5": ("volume", V / vavg >= 1.5),
    "rel volume>=2.5": ("volume", V / vavg >= 2.5),
    "volume accel (3d avg >1.5x 20d)": ("volume", V.rolling(3).mean() / vavg >= 1.5),
    # price structure
    "closes above previous day high": ("structure", C > H.shift(1)),
    "closes above 20-day high": ("structure", brk20),
    "breaks 20d high after >=15-bar base": ("structure", brk20 & (cons.shift(1) >= 15)),
    "break candle > 1.5 ATR": ("structure", brk20 & ((C - pc) > 1.5 * atr.shift(1))),
    "break after >=3 earlier tests of level": ("structure", brk20 & (nearhi >= 3)),
    "retest of broken level holds": (
        "structure",
        (C > lvl) & (L <= 1.01 * lvl) & ~brk20 & lvl.notna(),
    ),
    "extended (>3 ATR over EMA20)": ("structure", (C - e20) > 3 * atr),
    "within 5% of 52-week high": ("structure", C >= 0.95 * hi52),
    "new 52-week high": ("structure", C > hi52),
    # market context
    "market (Nifty) in uptrend": ("context", row2d(mk_up)),
    "sector 20d beat market": ("context", secret.gt(ret20.mean(axis=1), axis=0)),
    "breadth > 60% above 50d": ("context", row2d(breadth > 0.6)),
    "stock 60d beat Nifty 60d": ("context", ret60.gt(nret, axis=0)),
}
REG = {
    "Nifty up": row2d(mk_up),
    "Nifty down": row2d(mk_dn),
    "Nifty sideways": row2d(mk_side),
    "high-vol market": row2d(mk_hv),
    "low-vol market": row2d(~mk_hv),
}

# ---------------------------------------------------------------- outcomes and universe
turn = (C * V).rolling(20, min_periods=15).mean() / 1e7
bad = pd.DataFrame(False, index=C.index, columns=C.columns)
for iid, exd in splits:
    if iid in bad.columns:
        i = int(np.searchsorted(idx, np.datetime64(exd)))
        bad.iloc[max(0, i - 25) : min(T, i + 22), bad.columns.get_loc(iid)] = True
base_ok = (turn >= a.min_turnover_cr) & ~bad & atr.notna()
out: dict[int, dict[str, np.ndarray]] = {}
for h in HZS:
    fw = C.shift(-h) / C - 1
    ok = (base_ok & fw.notna()).to_numpy()
    hmax, lmin = H.rolling(h).max().shift(-h), L.rolling(h).min().shift(-h)
    out[h] = dict(
        ok=ok,
        fw=fw.to_numpy(),
        ex=fw.sub(fw.where(ok).median(axis=1), axis=0).to_numpy(),
        mfe=(hmax / C - 1).to_numpy(),
        mae=(lmin / C - 1).to_numpy(),
        rng=((hmax - lmin) / atr).to_numpy(),
    )
day = np.broadcast_to(np.arange(T)[:, None], (T, S))
per = np.where(idx >= HOLD0, 2, np.where(idx >= VAL0, 1, 0))[:, None]  # 0 DEV, 1 VAL, 2 HOLD
PN = {0: "DEV", 1: "VAL", 2: "HOLD"}
print(
    f"{S} stocks, {T} days {str(idx[0])[:10]}..{str(idx[-1])[:10]}; turnover >= {a.min_turnover_cr} Cr; round-trip cost {a.cost_pct}%"
)

TESTS: list[dict] = []


def stats(mask: np.ndarray, h: int, p: int) -> dict:
    o = out[h]
    sel = mask & o["ok"] & (per == p)
    n = int(sel.sum())
    r = dict(
        n=n,
        mean=np.nan,
        med=np.nan,
        pos=np.nan,
        mfe=np.nan,
        mae=np.nan,
        edge=np.nan,
        t=np.nan,
        net=np.nan,
    )
    if n < 100:
        return r
    fw, ex = o["fw"][sel], o["ex"][sel]
    bm = o["ex"][o["ok"] & (per == p)].mean()
    d = day[sel]
    cnt = np.bincount(d, minlength=T)
    pw = (np.bincount(d, weights=ex - bm, minlength=T)[cnt > 0] / cnt[cnt > 0])[
        ::h
    ]  # non-overlapping days
    t = (
        pw.mean() / (pw.std(ddof=1) / math.sqrt(len(pw)))
        if len(pw) > 5 and pw.std(ddof=1) > 0
        else np.nan
    )
    r.update(
        mean=100 * fw.mean(),
        med=100 * np.median(fw),
        pos=100 * (fw > 0).mean(),
        mfe=100 * np.nanmean(o["mfe"][sel]),
        mae=100 * np.nanmean(o["mae"][sel]),
        edge=100 * (ex.mean() - bm),
        t=t,
        net=100 * fw.mean() - a.cost_pct,
    )
    return r


def line(name: str, mask: np.ndarray, hs=HZS, ps=(0, 1), log=True, group="") -> None:
    for h in hs:
        cells = []
        for p in ps:
            s = stats(mask, h, p)
            if log:
                TESTS.append(dict(name=name, group=group, h=h, per=PN[p], **s))
            cells.append(
                f"{PN[p]} n={s['n']:>7,} mean{s['mean']:+5.2f} med{s['med']:+5.2f} up{s['pos']:5.1f}% mfe{s['mfe']:+5.1f} mae{s['mae']:+5.1f} edge{s['edge']:+5.2f} t{s['t']:+5.1f} net{s['net']:+5.2f}"
            )
        print(f"{name[:46]:<46} {h:>2}d  " + " | ".join(cells))


FA = {k: v[1].fillna(False).to_numpy().astype(bool) for k, v in F.items()}
RA = {k: v.to_numpy().astype(bool) for k, v in REG.items()}
ONE = np.ones((T, S), dtype=bool)

print("\n=== 1. every day (the baseline) and each feature alone")
line("ALL liquid stock-days", ONE, group="base")
for k, (grp, _) in F.items():
    line(k, FA[k], group=grp)

print("\n=== 2. each feature inside each market regime (10 sessions)")
for k in F:
    if k == "market (Nifty) in uptrend":
        continue
    for rn, rm in RA.items():
        line(f"{k} | {rn}", FA[k] & rm, hs=(10,), group="regime:" + rn)

print("\n=== 3. stacked: each added condition, and what it does to the count")
m = ONE
for nm, k in [
    ("RSI>60", "RSI>60"),
    ("+ market trending up", "market (Nifty) in uptrend"),
    ("+ rel volume>=1.5", "rel volume>=1.5"),
    ("+ closes above 20-day high", "closes above 20-day high"),
]:
    m = m & FA[k]
    line("chain " + nm, m, group="chain")
line(
    "breakout+vol+mkt up+sector",
    FA["closes above 20-day high"]
    & FA["rel volume>=1.5"]
    & FA["market (Nifty) in uptrend"]
    & FA["sector 20d beat market"],
    group="chain",
)
line(
    "breakout+vol, Nifty NOT up",
    FA["closes above 20-day high"] & FA["rel volume>=1.5"] & ~RA["Nifty up"],
    group="chain",
)

print(
    "\n=== 4. 20-day-high breakouts: features of those that worked (10-session excess > 0) vs failed, DEV+VAL"
)
o = out[10]
sel = FA["closes above 20-day high"] & o["ok"] & (per <= 1)
win = (o["ex"] > 0)[sel]
feat = {
    "rel volume": (V / vavg).to_numpy(),
    "base length (bars)": cons.shift(1).to_numpy(),
    "break candle / ATR": ((C - pc) / atr.shift(1)).to_numpy(),
    "extension over EMA20 / ATR": ((C - e20) / atr).to_numpy(),
    "distance to 52w high %": (100 * (1 - C / hi52)).to_numpy(),
    "earlier tests of level": nearhi.to_numpy(),
    "RSI": rsi.to_numpy(),
    "ADX": adx.to_numpy(),
    "Nifty uptrend (share)": RA["Nifty up"].astype(float),
    "high-vol market (share)": RA["high-vol market"].astype(float),
    "sector beat market (share)": FA["sector 20d beat market"].astype(float),
    "breadth": row2d(breadth).to_numpy(),
}
print(
    f"{'feature':<28}{'worked':>10}{'failed':>10}{'diff (sd)':>11}   n={int(sel.sum()):,}, worked {100 * win.mean():.1f}%"
)
for k, x in feat.items():
    v = np.asarray(x, dtype=float)[sel]
    g = np.isfinite(v)
    w, f_ = v[g & win], v[g & ~win]
    sdv = v[g].std()
    print(
        f"{k:<28}{w.mean():>10.2f}{f_.mean():>10.2f}{(w.mean() - f_.mean()) / sdv if sdv else 0:>+11.2f}"
    )

print(
    "\n=== 5. opportunity vs direction (10 sessions): does it raise the odds of a BIG move (range > 4 ATR), and which way when big?"
)
o = out[10]
big = o["rng"] > 4
for p in (0, 1):
    allm = o["ok"] & (per == p) & np.isfinite(o["rng"])
    print(
        f"{PN[p]} base: big move {100 * big[allm].mean():.1f}%, up when big {100 * (o['fw'] > 0)[allm & big].mean():.1f}%"
    )
print(
    f"{'feature':<40}{'DEV P(big)':>11}{'VAL P(big)':>11}{'DEV up|big':>11}{'VAL up|big':>11}{'n DEV':>10}"
)
for k in F:
    cells, ups, n0 = [], [], 0
    for p in (0, 1):
        s = FA[k] & o["ok"] & (per == p) & np.isfinite(o["rng"])
        b = s & big
        n0 = int(s.sum()) if p == 0 else n0
        cells.append(f"{100 * big[s].mean():>10.1f}%" if s.sum() > 100 else f"{'-':>11}")
        ups.append(f"{100 * (o['fw'] > 0)[b].mean():>10.1f}%" if b.sum() > 100 else f"{'-':>11}")
    print(f"{k:<40}{cells[0]}{cells[1]}{ups[0]}{ups[1]}{n0:>10,}")

print(
    "\n=== 6. is the big-move lift real? Same-stratum control: each feature's P(big) against what days with the SAME ATR%, recent-vol ratio and same-day range had anyway"
)
atrp = (atr / C).to_numpy()
r5 = (tr.rolling(5).mean() / tr.rolling(20).mean()).to_numpy()
tdy = (tr / atr.shift(1)).to_numpy()
okc = o["ok"] & np.isfinite(o["rng"]) & np.isfinite(r5) & np.isfinite(tdy)
qe = np.nanquantile(atrp[okc & (per == 0)], [0.2, 0.4, 0.6, 0.8])
strat = (
    np.digitize(np.nan_to_num(atrp), qe) * 9
    + np.digitize(np.nan_to_num(r5), [0.8, 1.2]) * 3
    + np.digitize(np.nan_to_num(tdy), [1.0, 1.5])
)
defs = {
    "A range>4 ATR": o["rng"] > 4,
    "B |move|>3 ATR%": np.maximum(np.abs(np.nan_to_num(o["mfe"])), np.abs(np.nan_to_num(o["mae"])))
    > 3 * atrp,
}
print(
    f"{'feature':<40}"
    + "".join(f"{d_[:2] + ' ' + pn:>22}" for d_ in defs for pn in ("DEV raw/ctl", "VAL raw/ctl"))
    + f"{'n DEV':>9}"
)
for k in list(F):
    cells = []
    for bg in defs.values():
        for p in (0, 1):
            m_ = okc & (per == p)
            rate = np.bincount(strat[m_], weights=bg[m_], minlength=45) / np.maximum(
                np.bincount(strat[m_], minlength=45), 1
            )
            sel = FA[k] & m_
            if sel.sum() < 200:
                cells.append(f"{'-':>22}")
                continue
            base = bg[m_].mean()
            cells.append(
                f"{bg[sel].mean() / base:>10.2f}x /{bg[sel].mean() / rate[strat[sel]].mean():>5.2f}x   "
            )
    print(f"{k:<40}{''.join(cells)}{int((FA[k] & okc & (per == 0)).sum()):>9,}")

# ---------------------------------------------------------------- survivors (frozen from DEV + VAL) and the holdout
N = len({(t["name"], t["h"]) for t in TESTS})
tcrit = NormalDist().inv_cdf(1 - 0.05 / 2 / max(N, 1))
print(
    f"\n=== survivors: {N} hypotheses tested; Bonferroni |t| >= {tcrit:.2f} in DEV, same sign and t >= 2 in VAL, n >= 1000 DEV / 300 VAL, and (for a long) positive net of {a.cost_pct}% cost in both"
)
dev = {(t["name"], t["h"]): t for t in TESTS if t["per"] == "DEV"}
val = {(t["name"], t["h"]): t for t in TESTS if t["per"] == "VAL"}
surv: list[tuple[str, int]] = []
for key, d_ in dev.items():
    v_ = val.get(key)
    if (
        v_ is None
        or key[0].startswith("ALL")
        or d_["n"] < 1000
        or v_["n"] < 300
        or not np.isfinite(d_["t"])
        or not np.isfinite(v_["t"])
    ):
        continue
    sg = np.sign(d_["edge"])
    if (
        abs(d_["t"]) >= tcrit
        and sg * v_["t"] >= 2
        and sg == np.sign(v_["edge"])
        and (sg < 0 or (d_["net"] > 0 and v_["net"] > 0))
    ):
        surv.append(key)
        print(
            f"{key[0][:60]:<60} {key[1]:>2}d  DEV edge{d_['edge']:+5.2f} t{d_['t']:+5.1f} n={d_['n']:,} | VAL edge{v_['edge']:+5.2f} t{v_['t']:+5.1f} n={v_['n']:,} | net {d_['net']:+5.2f}/{v_['net']:+5.2f}"
        )
if not surv:
    print("(none survived)")
if a.final:
    print(
        "\n=== HOLDOUT 2024+ (once, single features only; a stacked or regime row must be re-run by hand)"
    )
    for nm, h in surv:
        if nm in FA:
            line(nm, FA[nm], hs=(h,), ps=(2,), log=False)
        else:
            print(f"{nm} {h}d: stacked/regime row, evaluate by hand")
if a.log:
    pd.DataFrame(TESTS).to_csv(a.log, index=False)
    print(f"wrote {len(TESTS)} test rows to {a.log}")
