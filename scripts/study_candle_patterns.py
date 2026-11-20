# ruff: noqa: E501
"""Study: do the candlestick patterns the chart marks (frontend/lib/autoAnalysis.ts `patterns`) predict anything?

The detector is replayed here with the same rules and the same priority (one pattern per bar; the first rule that matches wins, and a hammer-shaped or
inside-bar bar is used up even when its trend check fails). Run over every liquid NSE stock since late 2019. Everything is known at the close of the pattern's
last bar; the return runs from that close: close(+H sessions) / close - 1, less the median stock that day. Bullish patterns are read as-is, bearish ones signed
the other way, so + always means "it went the way the pattern says". `edge` is the mean against what a random stock does in that direction (random stocks drift
up, so a bullish pattern must beat +mean and a bearish one must beat -mean). A window that crosses a split or bonus is dropped.
usage: study_candle_patterns.py [--db URL] [--horizon 10] [--min-turnover-cr 5] [--check SYMBOL]   (--check prints that stock's marks to compare with the chart)"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS  # noqa: E402,I001

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--horizon", type=int, default=10)
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
ap.add_argument("--check", help="print the marks for one symbol")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
HZ = a.horizon

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-09-01' ORDER BY instrument_id, ts, dataset_version DESC"
    ).fetchall()
    splits = conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ).fetchall()
    symbols = dict(
        conn.execute(
            "SELECT instrument_id, symbol FROM instrument WHERE asset_class='equity'"
        ).fetchall()
    )

df = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
del rows


def mat(frame: pd.DataFrame, col: str) -> pd.DataFrame:
    return frame.pivot(index="d", columns="iid", values=col).sort_index()


Op, H, L, C, V = (mat(df, k) for k in ("o", "h", "l", "c", "v"))
del df
R = H - L
body = (C - Op).abs()
up, down = C > Op, C < Op
avg = R.shift(1).rolling(14, min_periods=14).mean()
top, bottom = Op.where(Op > C, C), Op.where(Op < C, C)  # the body's upper and lower edge
lower, upper = bottom - L, H - top


def sh(x: pd.DataFrame, k: int) -> pd.DataFrame:
    return x.shift(k)


def big(
    k: int,
) -> pd.DataFrame:  # a bar k back with a body of at least half the average bar (judged against the average at the last bar, as the chart does)
    return sh(body, k) >= 0.5 * avg


def fell(
    k: int,
) -> (
    pd.DataFrame
):  # the bar before bar i-k closed below the one four bars earlier: a fall into the pattern
    return sh(C, k + 1) < sh(C, k + 5)


def rose(k: int) -> pd.DataFrame:
    return sh(C, k + 1) > sh(C, k + 5)


# inside-bar break, as the chart: a run of clearly smaller inside bars (<= 60% of the mother), mother >= average bar, then the first close beyond the mother
ins = (H < sh(H, 1)) & (L > sh(L, 1))
iv, rr = ins.to_numpy(), R.fillna(0).to_numpy()
rv, mv = np.zeros(iv.shape, dtype=int), np.zeros(iv.shape)
for t in range(1, len(C.index)):
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
    mh, ml = mh.where(~sel, sh(H, k + 1)), ml.where(~sel, sh(L, k + 1))
mr = mh - ml
ib_setup = (run.shift(1) >= 1) & (mr >= avg) & (runmax.shift(1) <= 0.6 * mr)
ib_up, ib_down = ib_setup & (C > mh), ib_setup & (C < ml)
sma50 = C.rolling(50, min_periods=50).mean()
uptrend = (sh(C, 1) > sma50) & (
    sma50 > sma50.shift(10)
)  # sma50 needs 50 bars and its 10-bar-ago value 60, as the chart requires

soldiers = (
    up
    & sh(up, 1)
    & sh(up, 2)
    & big(0)
    & big(1)
    & big(2)
    & (C > sh(C, 1))
    & (sh(C, 1) > sh(C, 2))
    & (Op > sh(Op, 1))
    & (sh(Op, 1) > sh(Op, 2))
    & fell(2)
)
crows = (
    down
    & sh(down, 1)
    & sh(down, 2)
    & big(0)
    & big(1)
    & big(2)
    & (C < sh(C, 1))
    & (sh(C, 1) < sh(C, 2))
    & (Op < sh(Op, 1))
    & (sh(Op, 1) < sh(Op, 2))
    & rose(2)
)
mid2 = (sh(Op, 2) + sh(C, 2)) / 2
morning = sh(down, 2) & big(2) & (sh(body, 1) <= 0.3 * sh(body, 2)) & up & (C > mid2) & fell(2)
evening = sh(up, 2) & big(2) & (sh(body, 1) <= 0.3 * sh(body, 2)) & down & (C < mid2) & rose(2)
bull_eng = (
    sh(down, 1) & up & (Op <= sh(C, 1)) & (C >= sh(Op, 1)) & (body > sh(body, 1)) & big(0) & fell(0)
)
bear_eng = (
    sh(up, 1) & down & (Op >= sh(C, 1)) & (C <= sh(Op, 1)) & (body > sh(body, 1)) & big(0) & rose(0)
)
hammer_shape = (R >= 0.5 * avg) & (lower >= 2 * body) & (upper <= 0.5 * body) & (body > 0)
star_shape = (R >= 0.5 * avg) & (upper >= 2 * body) & (lower <= 0.5 * body) & (body > 0) & rose(0)
doji = (R >= 0.7 * avg) & (body <= 0.1 * R)

# rule branches in the chart's order: the first whose condition holds takes the bar (labels inside a branch split it by what the bar shows)
Branch = tuple[pd.DataFrame, list[tuple[str, pd.DataFrame | None, int]]]
branches: list[Branch] = [
    (soldiers, [("3 white soldiers", None, 1)]),
    (crows, [("3 black crows", None, -1)]),
    (
        ib_up | ib_down,
        [
            ("Inside-bar breakout, with trend", ib_up & uptrend, 1),
            ("Inside-bar breakout, other (weak)", ib_up & ~uptrend, 1),
            ("Inside-bar breakdown (weak)", ib_down, -1),
        ],
    ),
    (morning, [("Morning star", None, 1)]),
    (evening, [("Evening star", None, -1)]),
    (bull_eng, [("Bullish engulfing", None, 1)]),
    (bear_eng, [("Bearish engulfing", None, -1)]),
    (
        hammer_shape,
        [("Hammer", fell(0), 1), ("Hanging man", rose(0) & ~fell(0), -1)],
    ),  # the branch is used up even when neither trend fits
    (star_shape, [("Shooting star", None, -1)]),
    (doji, [("Doji", None, 0)]),
]
used = pd.DataFrame(False, index=C.index, columns=C.columns)
labelled: dict[str, pd.DataFrame] = {}
signs: dict[str, int] = {}
ok = avg > 0
for cond, labels in branches:
    cond = cond.fillna(False).astype(bool) & ok
    take = cond & ~used
    for name, refine, sign in labels:
        labelled[name] = take if refine is None else take & refine.fillna(False).astype(bool)
        signs[name] = sign
    used = used | cond

if a.check:
    iid = next(i for i, s in symbols.items() if s == a.check and i in C.columns)
    for name, m in labelled.items():
        for d in m.index[m[iid].to_numpy()]:
            print(d, name)
    sys.exit()

turnover = (C * V).rolling(20, min_periods=15).mean() / 1e7
fwd = C.shift(-HZ) / C - 1
bad = pd.DataFrame(False, index=C.index, columns=C.columns)
idx = C.index.values
for iid, ex_date in splits:
    if iid in bad.columns:
        i = int(np.searchsorted(idx, np.datetime64(ex_date)))
        bad.iloc[max(0, i - 25) : min(len(idx), i + HZ + 1), bad.columns.get_loc(iid)] = True
liquid = (turnover >= a.min_turnover_cr) & ~bad & fwd.notna()
ex = fwd.sub(fwd.where(liquid).median(axis=1), axis=0)
base = ex.where(liquid).stack().dropna()
bm = base.mean()
print(
    f"horizon {HZ} sessions, turnover >= {a.min_turnover_cr} Cr. A random stock: beats the market {100 * (base > 0).mean():.1f}%, mean {100 * bm:+.2f}% (so a bullish pattern must beat {100 * bm:+.2f}%, a bearish one {-100 * bm:+.2f}%).\n"
)
print(
    f"{'pattern':<38}{'signals':>8}{'went its way %':>16}{'median %':>10}{'mean %':>9}{'edge %':>8}{'t (edge)':>10}"
)
for name, m in labelled.items():
    e = ex.where(m & liquid).stack().dropna()
    if len(e) < 30:
        print(f"{name:<38}{len(e):>8}")
        continue
    s = signs[name]
    if s == 0:  # a doji says nothing about direction: report the move either way
        pw = e.groupby(level=0).mean() - bm
        t = pw.mean() / (pw.std() / np.sqrt(len(pw)))
        print(
            f"{name:<38}{len(e):>8,}{100 * (e > 0).mean():>16.1f}{100 * e.median():>10.2f}{100 * e.mean():>9.2f}{100 * (e.mean() - bm):>8.2f}{t:>10.2f}"
        )
        continue
    se = e * s
    edge = se - s * bm
    pw = edge.groupby(level=0).mean()
    t = pw.mean() / (pw.std() / np.sqrt(len(pw))) if len(pw) > 5 and pw.std() > 0 else float("nan")
    print(
        f"{name:<38}{len(e):>8,}{100 * (se > 0).mean():>16.1f}{100 * se.median():>10.2f}{100 * se.mean():>9.2f}{100 * edge.mean():>8.2f}{t:>10.2f}"
    )
