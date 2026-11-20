# ruff: noqa: E501
"""Search: which early-signal combinations, within what window of days, really precede a rise? Tuned on 2019-2023, judged on 2024 onward.

Twelve bullish conditions are computed on daily bars of every liquid NSE stock (all causal: each is known at its bar's close):
  volume     closes up on >= 1.5x its 20-day average volume          macd       MACD(12,26,9) crosses above its signal line
  breakout   close above the previous 20 bars' highest high           high52     close above the previous 252 bars' highest high
  rsi50      RSI(14) crosses up through 50                            rsi30      RSI(14) crosses up through 30
  reclaim    close crosses above the 50-day average                   ema_cross  EMA(9) crosses above EMA(21)
  golden     50-day average crosses above the 200-day average         trendline  close breaks above the falling line through the last two confirmed swing highs
  squeeze    close above the upper Bollinger band right after a squeeze (bandwidth < 0.8x its 120-bar mean)
  ibtrend    inside-bar breakout with an uptrend
A condition counts as true for the `window` bars it fires on and after, so signs on different days count together. A signal is the first bar on which at least `k`
distinct conditions are true. Return: close(+H) / close - 1, less the median stock that day. `edge` = mean less a random stock's mean (stocks drift up); `beat %` = share beating
the median stock (50 = none); t is by day. Splits/bonuses are dropped. IS = 2019-2023 (where choices are made), OOS = 2024 (never used to choose).
HOLDOUT: bars stop before config/research_holdout.json holdout_start (2025-01-01). Runs before 2026-11-19 had no upper bound and read 2025-2026: those results are CONTAMINATED
(they fed TODO 6.14/6.15, i.e. removing the chart's checklist signs and the rise-odds work); do not select combinations from them.
usage: study_signal_search.py [--db URL] [--horizon 10] [--min-turnover-cr 5]"""

import argparse
import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS  # noqa: E402,I001

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--horizon", type=int, default=10)
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
ap.add_argument(
    "--base", action="store_true", help="also test the sideways-base-then-volume-surge setup"
)
ap.add_argument(
    "--score",
    action="store_true",
    help="also test the signals filtered by the stock's swing score and by how far it has already run",
)
ap.add_argument(
    "--own",
    action="store_true",
    help="judge the stock's OWN forward return (beat % = share that rose) instead of beating the median stock",
)
ap.add_argument(
    "--down",
    action="store_true",
    help="only stocks in a downtrend 5 bars before (close under a falling 50-day average); the benchmark is a random downtrend stock",
)
ap.add_argument(
    "--rule",
    action="store_true",
    help="owner's rule: MACD above its signal AND EMA9 above EMA21 AND >= 1 (or 2) of volume/breakout/rsi-rising/reclaim/trendline/squeeze/high52 in the last 3 bars; first in a 10-bar streak",
)
ap.add_argument(
    "--check",
    help="print one symbol's 3+ aligned (window 5, all 12) signals and first-in-streak 52-week highs, to compare with the chart",
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
HZ = a.horizon
SPLIT_DAY = np.datetime64("2024-01-01")
END = json.loads(
    (Path(__file__).resolve().parents[1] / "config/research_holdout.json").read_text()
)["holdout_start"]

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-09-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC",
        (END,),
    ).fetchall()
    splits = conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ).fetchall()

df = pd.DataFrame(rows, columns=["iid", "d", "h", "l", "c", "v", "dq"])
del rows


def mat(frame: pd.DataFrame, col: str) -> pd.DataFrame:
    return frame.pivot(index="d", columns="iid", values=col).sort_index()


H, L, C, V, DQ = (mat(df, k) for k in ("h", "l", "c", "v", "dq"))
del df
T, S = C.shape
R = H - L
avg14 = R.shift(1).rolling(14, min_periods=14).mean()
sma20, sma50, sma200 = (C.rolling(n, min_periods=n).mean() for n in (20, 50, 200))


def crossed_up(x: pd.DataFrame, y: pd.DataFrame) -> pd.DataFrame:
    return (x > y) & (x.shift(1) <= y.shift(1))


c: dict[str, pd.DataFrame] = {}
c["volume"] = (V >= 1.5 * V.shift(1).rolling(20, min_periods=15).mean()) & (C > C.shift(1))
macd = C.ewm(span=12, adjust=False).mean() - C.ewm(span=26, adjust=False).mean()
c["macd"] = crossed_up(macd, macd.ewm(span=9, adjust=False).mean())
c["breakout"] = C > H.shift(1).rolling(20, min_periods=20).max()
c["high52"] = C > H.shift(1).rolling(252, min_periods=200).max()
dl = C.diff()
rsi = 100 - 100 / (
    1
    + dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
)
c["rsi50"] = crossed_up(rsi, rsi * 0 + 50)
c["rsi30"] = crossed_up(rsi, rsi * 0 + 30)
c["reclaim"] = crossed_up(C, sma50)
c["ema_cross"] = crossed_up(C.ewm(span=9, adjust=False).mean(), C.ewm(span=21, adjust=False).mean())
c["golden"] = crossed_up(sma50, sma200)
sd20 = C.rolling(20, min_periods=20).std()
bw = 4 * sd20 / sma20
c["squeeze"] = (bw < 0.8 * bw.rolling(120, min_periods=60).mean()).shift(1, fill_value=False) & (
    C > sma20 + 2 * sd20
)

# trendline breakout: the falling line through the last two swing highs confirmed 5 bars after they formed (so nothing here looks ahead)
rowno = pd.DataFrame(
    np.broadcast_to(np.arange(T)[:, None], (T, S)).astype(float), index=C.index, columns=C.columns
)
swing = (H == H.rolling(11, center=True, min_periods=11).max()) & (H != H.shift(1))
j_at, p_at = rowno.where(swing), H.where(swing)
last_j, last_p = j_at.shift(5).ffill(), p_at.shift(5).ffill()
prev_j = j_at.ffill().shift(1).where(swing).shift(5).ffill()
prev_p = p_at.ffill().shift(1).where(swing).shift(5).ffill()
slope = (last_p - prev_p) / (last_j - prev_j)
line = last_p + slope * (rowno - last_j)
c["trendline"] = (slope < 0) & ((rowno - last_j) <= 120) & (C > line) & (C.shift(1) <= line - slope)
del j_at, p_at, last_j, last_p, prev_j, prev_p, slope, line, rowno

ins = (H < H.shift(1)) & (L > L.shift(1))
iv, rr = ins.to_numpy(), R.fillna(0).to_numpy()
rv, mv = np.zeros(iv.shape, dtype=int), np.zeros(iv.shape)
for t in range(1, T):
    rv[t] = np.where(iv[t], rv[t - 1] + 1, 0)
    mv[t] = np.where(iv[t], np.maximum(mv[t - 1], rr[t]), 0.0)
run, runmax = (
    pd.DataFrame(rv, index=C.index, columns=C.columns),
    pd.DataFrame(mv, index=C.index, columns=C.columns),
)
mh, ml = (
    pd.DataFrame(np.nan, index=C.index, columns=C.columns),
    pd.DataFrame(np.nan, index=C.index, columns=C.columns),
)
for k in range(1, 40):
    sel = run.shift(1) == k
    mh, ml = mh.where(~sel, H.shift(k + 1)), ml.where(~sel, L.shift(k + 1))
mr = mh - ml
c["ibtrend"] = (
    (run.shift(1) >= 1)
    & (mr >= avg14)
    & (runmax.shift(1) <= 0.6 * mr)
    & (C > mh)
    & (C.shift(1) > sma50)
    & (sma50 > sma50.shift(10))
)
del run, runmax, mh, ml, mr, ins, iv, rr, rv, mv

NAMES = list(c)
if a.check:
    with psycopg.connect(a.db) as conn2:
        iid = conn2.execute(
            "SELECT instrument_id FROM instrument WHERE symbol=%s AND asset_class='equity' ORDER BY instrument_id",
            (a.check,),
        ).fetchall()
    col = next(i[0] for i in iid if i[0] in C.columns)
    rec = {k: c[k][col].fillna(False).astype(float).rolling(5, min_periods=1).max() for k in NAMES}
    cnt = sum(rec.values())
    for dd in C.index[((cnt >= 3) & (cnt.shift(1) < 3)).to_numpy()]:
        print("ALIGN", dd, "+".join(k for k in NAMES if rec[k][dd] == 1))
    h52c = c["high52"][col].fillna(False)
    fst = h52c & ~h52c.shift(1, fill_value=False).astype(bool).rolling(
        10, min_periods=1
    ).max().astype(bool)
    for dd in C.index[fst.to_numpy()]:
        print("HIGH52", dd)
    sys.exit()
turnover = (C * V).rolling(20, min_periods=15).mean() / 1e7
fwd = C.shift(-HZ) / C - 1
bad = pd.DataFrame(False, index=C.index, columns=C.columns)
idx = C.index.values
for iid, ex_date in splits:
    if iid in bad.columns:
        i = int(np.searchsorted(idx, np.datetime64(ex_date)))
        bad.iloc[max(0, i - 25) : min(T, i + HZ + 1), bad.columns.get_loc(iid)] = True
liquid = ((turnover >= a.min_turnover_cr) & ~bad & fwd.notna()).to_numpy()
if a.down:
    liquid = (
        liquid & ((C < sma50) & (sma50 < sma50.shift(20))).shift(5, fill_value=False).to_numpy()
    )
ex = fwd.to_numpy() if a.own else fwd.sub(fwd.where(liquid).median(axis=1), axis=0).to_numpy()
day = np.nonzero(liquid)[
    0
]  # the row (day) of every liquid cell, in the same order as the flattened arrays below
ex_f = ex[liquid]
oos = idx[day] >= SPLIT_DAY
bm_is, bm_oos = ex_f[~oos].mean(), ex_f[oos].mean()
print(
    f"horizon {HZ} sessions, turnover >= {a.min_turnover_cr} Cr. Random stock: mean {100 * bm_is:+.2f}% in 2019-23 (IS), {100 * bm_oos:+.2f}% from 2024 (OOS); beats the median stock {100 * (ex_f[~oos] > 0).mean():.1f}% / {100 * (ex_f[oos] > 0).mean():.1f}%.\n"
)


def stat(mask: np.ndarray, part: np.ndarray, bm: float) -> tuple[int, float, float, float]:
    sel = mask & part
    n = int(sel.sum())
    if n < 200:
        return n, float("nan"), float("nan"), float("nan")
    e = ex_f[sel] - bm
    d = day[sel]
    cnt = np.bincount(d, minlength=T)
    tot = np.bincount(d, weights=e, minlength=T)
    pw = tot[cnt > 0] / cnt[cnt > 0]
    t = (
        pw.mean() / (pw.std(ddof=1) / np.sqrt(len(pw)))
        if len(pw) > 5 and pw.std(ddof=1) > 0
        else float("nan")
    )
    return n, 100 * (ex_f[sel] > 0).mean(), 100 * e.mean(), t


def both(mask_matrix: np.ndarray) -> str:
    m = mask_matrix[liquid]
    n1, b1, e1, t1 = stat(m, ~oos, bm_is)
    n2, b2, e2, t2 = stat(m, oos, bm_oos)
    return f"IS {n1:>7,} beat {b1:5.1f} edge {e1:+5.2f} t {t1:+5.1f} | OOS {n2:>7,} beat {b2:5.1f} edge {e2:+5.2f} t {t2:+5.1f}"


if a.rule:
    macd_pos = macd > macd.ewm(span=9, adjust=False).mean()
    ema_up = C.ewm(span=9, adjust=False).mean() > C.ewm(span=21, adjust=False).mean()
    pool = dict.fromkeys(["volume", "breakout", "reclaim", "trendline", "squeeze", "high52"])
    rec3 = {k: c[k].fillna(False).astype(float).rolling(3, min_periods=1).max() for k in pool}
    rec3["rsi_up"] = (
        (rsi > rsi.shift(1)) & (rsi.shift(1) > rsi.shift(2)) & (rsi.shift(2) > rsi.shift(3))
    ).astype(float)
    n_pool = sum(rec3.values())
    base = (macd_pos & ema_up).to_numpy()
    for need in (1, 2, 3):
        on = base & (n_pool >= need).to_numpy()
        seen = (
            pd.DataFrame(on)
            .rolling(10, min_periods=1)
            .max()
            .shift(1, fill_value=0)
            .to_numpy()
            .astype(bool)
        )
        print(
            f"MACD>signal + EMA9>EMA21 + >= {need} of 7 extra (3 bars), first in streak: {both(on & ~seen)}"
        )
    sys.exit()

print("=== each condition alone (the bar it fires on)")
for k in NAMES:
    print(f"{k:<12}{both(c[k].fillna(False).to_numpy())}")
print()

windows = (2, 3, 5, 7, 10)
recent: dict[tuple[str, int], np.ndarray] = {}
for w in windows:
    for k in NAMES:
        recent[(k, w)] = c[k].fillna(False).astype(float).rolling(w, min_periods=1).max().to_numpy()
print("=== at least K of the 12 within W days (first bar the count reaches K)")
for w in windows:
    cnt = sum(recent[(k, w)] for k in NAMES)
    prev = np.vstack([np.zeros((1, S)), cnt[:-1]])
    for need in (2, 3, 4, 5):
        print(f"W={w:<3}K>={need}  {both((cnt >= need) & (prev < need))}")
    print()

print("=== triples (window 5): the 12 best by in-sample t, shown with how they did out of sample")
res = []
w = 5
for combo in itertools.combinations(NAMES, 3):
    allin = np.minimum.reduce([recent[(k, w)] for k in combo]) == 1
    prev = np.vstack([np.zeros((1, S), dtype=bool), allin[:-1]])
    m = (allin & ~prev)[liquid]
    n1, b1, e1, t1 = stat(m, ~oos, bm_is)
    n2, b2, e2, t2 = stat(m, oos, bm_oos)
    if n1 >= 500 and not np.isnan(t1):
        res.append((t1, combo, n1, b1, e1, n2, b2, e2, t2))
res.sort(reverse=True)
print(f"{len(res)} triples with enough signals. Top of the IS ranking:")
for t1, combo, n1, b1, e1, n2, b2, e2, t2 in res[:12]:
    print(
        f"{'+'.join(combo):<38} IS {n1:>6,} beat {b1:5.1f} edge {e1:+5.2f} t {t1:+5.1f} | OOS {n2:>6,} beat {b2:5.1f} edge {e2:+5.2f} t {t2:+5.1f}"
    )
top = res[: max(1, len(res) // 10)]
print(
    f"\nOf the top 10% by IS t ({len(top)} triples): OOS edge positive in {sum(1 for r in top if r[7] > 0)}, OOS t > 2 in {sum(1 for r in top if r[8] > 2)}; mean OOS edge {np.nanmean([r[7] for r in top]):+.2f}%, mean OOS beat {np.nanmean([r[6] for r in top]):.1f}%"
)
print(
    f"Over all {len(res)} triples: mean OOS edge {np.nanmean([r[7] for r in res]):+.2f}%, mean OOS beat {np.nanmean([r[6] for r in res]):.1f}%, OOS t > 2 in {sum(1 for r in res if r[8] > 2)}, OOS t < -2 in {sum(1 for r in res if r[8] < -2)}"
)

print(
    "\n=== a new 52-week high: every day it closes above the prior 252-bar high, or only the first in a streak (not fired in the 10 bars before)"
)
h52 = c["high52"].fillna(False)
first = (
    h52 & ~h52.shift(1, fill_value=False).astype(bool).rolling(10, min_periods=1).max().astype(bool)
).to_numpy()
print(f"every day      {both(h52.to_numpy())}")
print(f"first in streak {both(first)}")
vol_ok = (h52 & c["volume"].fillna(False)).to_numpy()
print(f"with a volume surge that day {both(vol_ok)}")

print(
    "\n=== plain 'did the price go up' (not against the market): 3+ aligned (all 12, window 5) vs every liquid stock-day, 2024 onward and 2019-23"
)
raw = fwd.to_numpy()[liquid]
cnt5 = sum(recent[(k, 5)] for k in NAMES)
prev5 = np.vstack([np.zeros((1, S)), cnt5[:-1]])
sig5 = ((cnt5 >= 3) & (prev5 < 3))[liquid]
for name, part in (("2019-23", ~oos), ("2024+  ", oos)):
    for label, m in (("3+ aligned signal", sig5 & part), ("any stock-day    ", part)):
        r = raw[m]
        print(
            f"{name} {label}: {len(r):>9,} cases, up {100 * (r > 0).mean():.1f}%, up 3%+ {100 * (r > 0.03).mean():.1f}%, down 3%+ {100 * (r < -0.03).mean():.1f}%, median {100 * np.median(r):+.2f}%"
        )


if a.score:
    # the swing score as it stood on each past week (stock_score_history), carried forward to the days after it: known by that week's close, so it never looks ahead
    with psycopg.connect(a.db) as conn3:
        srows = conn3.execute(
            "SELECT day, instrument_id, score::float8 FROM stock_score_history"
        ).fetchall()
    sc = pd.DataFrame(srows, columns=["d", "iid", "score"]).pivot(
        index="d", columns="iid", values="score"
    )
    sc.index = pd.to_datetime(sc.index)
    SC = (
        sc.reindex(index=pd.to_datetime(C.index), columns=C.columns).ffill(limit=7).to_numpy()
    )  # up to a week of days after the reading
    ext60 = (C / C.shift(60) - 1).to_numpy()  # how far it has already run in 60 sessions
    ext50 = (C / sma50 - 1).to_numpy()  # and how far above its 50-day average
    off_low = (
        C / C.rolling(252, min_periods=200).min() - 1
    ).to_numpy()  # and above its 52-week low
    aligned3 = (cnt5 >= 3) & (prev5 < 3)
    sets = {
        "new 52-week high (first day)": first,
        "3+ aligned signs (5 days)": aligned3,
        "inside-bar breakout with trend": c["ibtrend"].fillna(False).to_numpy(),
        "squeeze breakout": c["squeeze"].fillna(False).to_numpy(),
    }

    print(
        "\n=== swing score alone, every stock-day (no signal): is a high score itself worth anything?"
    )
    for lo_, hi_ in ((0, 40), (40, 50), (50, 60), (60, 70), (70, 101)):
        print(f"score {lo_:>3}-{hi_:<3}       {both((SC >= lo_) & (SC < hi_))}")

    print(
        "\n=== how far the stock had already run when the signal fired (new 52-week high, first day): is earlier better?"
    )
    for name, lo_, hi_ in (
        ("fell over 60 days", -9, 0),
        ("rose 0-15%", 0, 0.15),
        ("rose 15-30%", 0.15, 0.30),
        ("rose 30-60%", 0.30, 0.60),
        ("rose over 60%", 0.60, 99),
    ):
        print(f"{name:<22}{both(first & (ext60 >= lo_) & (ext60 < hi_))}")

    print("\n=== each signal set: alone, with a good score, with 'not run too far yet', and both")
    for name, m in sets.items():
        print(f"-- {name}")
        print(f"   alone                          {both(m)}")
        for sv in (50, 60, 70):
            print(f"   score >= {sv}                    {both(m & (SC >= sv))}")
        for cap in (0.15, 0.30):
            print(f"   rose < {int(cap * 100)}% in 60 days         {both(m & (ext60 < cap))}")
        for sv in (50, 60, 70):
            for cap in (0.15, 0.30):
                print(
                    f"   score >= {sv} and rose < {int(cap * 100)}%     {both(m & (SC >= sv) & (ext60 < cap))}"
                )
    print(
        "\n=== early-cycle screen without a signal: score high, not run far, and close to a 52-week high"
    )
    for sv in (60, 70):
        print(
            f"score >= {sv}, rose < 30% in 60d, within 15% below its 52-wk high".ljust(60), end=""
        )
        near_high = (C / C.rolling(252, min_periods=200).max()).to_numpy() >= 0.85
        print(both((SC >= sv) & (ext60 < 0.30) & near_high))


if a.base:
    # sideways base, then a surge: the 40 bars before were a narrow range (high over low within `thr`), then volume surges (m times its 20-day average) on an up bar, possibly closing above the base's high
    hi40 = H.shift(1).rolling(40, min_periods=40).max()
    lo40 = L.shift(1).rolling(40, min_periods=40).min()
    base_range = (hi40 / lo40 - 1).to_numpy()
    base_prior = (
        H.shift(6).rolling(40, min_periods=40).max() / L.shift(6).rolling(40, min_periods=40).min()
        - 1
    ).to_numpy()  # the base as it was before a 5-day signal window began
    avgv = V.shift(1).rolling(20, min_periods=15).mean()
    up_bar = C > C.shift(1)
    out_of_base = (C > hi40).to_numpy()
    maxrun = (
        H.rolling(20).max().shift(-20) / C - 1
    ).to_numpy()  # the best price in the next 20 sessions, as a gain from this close
    maxdip = (L.rolling(20).min().shift(-20) / C - 1).to_numpy()  # and the worst
    liq_run = maxrun[liquid]
    liq_dip = maxdip[liquid]

    def first(
        ev: np.ndarray,
    ) -> np.ndarray:  # the first day of a streak: not true on any of the 10 days before
        e = pd.DataFrame(ev, index=C.index, columns=C.columns)
        return (
            e
            & ~e.shift(1, fill_value=False)
            .astype(bool)
            .rolling(10, min_periods=1)
            .max()
            .astype(bool)
        ).to_numpy()

    def tail(mask_matrix: np.ndarray) -> str:
        m = mask_matrix[liquid]
        out = []
        for name, part in (("IS ", ~oos), ("OOS", oos)):
            sel = m & part & ~np.isnan(liq_run)
            n = int(sel.sum())
            if n < 200:
                out.append(f"{name} {n:>6,} too few")
                continue
            out.append(
                f"{name} {n:>6,} +10% in 20d {100 * (liq_run[sel] >= 0.10).mean():4.1f}% (any day {100 * (liq_run[part & ~np.isnan(liq_run)] >= 0.10).mean():4.1f}%)  -8% in 20d {100 * (liq_dip[sel] <= -0.08).mean():4.1f}% (any day {100 * (liq_dip[part & ~np.isnan(liq_dip)] <= -0.08).mean():4.1f}%)"
            )
        return " | ".join(out)

    print(
        "\n=== sideways base then a volume surge. Edge/beat as before; then how often it gained 10%+ (and fell 8%+) within the next 20 sessions, against any liquid stock-day"
    )
    for thr in (0.15, 0.20, 0.30):
        for m in (1.5, 2.0, 3.0):
            surge = ((V >= m * avgv) & up_bar).to_numpy()
            ev = {
                "base + surge": surge & (base_range <= thr),
                "base + surge + out of the base": surge & (base_range <= thr) & out_of_base,
            }
            for name, e in ev.items():
                f = first(e)
                print(f"base<={int(thr * 100)}% surge>={m:.1f}x {name:<31}{both(f)}")
                print(f"{'':<54}{tail(f)}")
    print(
        "\n=== 3+ aligned signs (5 days) that began from a sideways base (the base as it was before the window)"
    )
    for thr in (0.15, 0.20, 0.30):
        al = aligned3 if "aligned3" in dir() else None
        e = ((cnt5 >= 3) & (prev5 < 3)) & (base_prior <= thr)
        print(f"base<={int(thr * 100)}% then 3+ aligned                 {both(e)}")
        print(f"{'':<54}{tail(e)}")
        ev = e & np.minimum.reduce([recent[("volume", 5)] == 1])
        print(f"  ... with a volume surge among them          {both(ev)}")
        print(f"{'':<54}{tail(ev)}")
    print(
        "\n=== sideways base, volume surge and the share taken for delivery (institutions keeping the shares, not trading them)"
    )
    dpct = (DQ / V.where(V > 0) * 100).to_numpy()
    dr = (DQ / V.where(V > 0) * 100) / (
        (DQ / V.where(V > 0) * 100).shift(1).rolling(20, min_periods=15).mean()
    )
    for thr in (0.20, 0.30):
        surge = ((V >= 2 * avgv) & up_bar).to_numpy()
        for dmin in (40, 50, 60):
            e = first(surge & (base_range <= thr) & (dpct >= dmin))
            print(f"base<={int(thr * 100)}% surge>=2x delivery>={dmin}%             {both(e)}")
            print(f"{'':<54}{tail(e)}")
        e = first(surge & (base_range <= thr) & (dr.to_numpy() >= 1.5))
        print(f"base<={int(thr * 100)}% surge>=2x delivery 1.5x its norm        {both(e)}")
        print(f"{'':<54}{tail(e)}")
    print("\n=== reference: any liquid stock-day")
    print(f"{'':<54}{tail(np.ones_like(base_range, dtype=bool))}")
