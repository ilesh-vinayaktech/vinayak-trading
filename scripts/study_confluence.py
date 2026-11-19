# ruff: noqa: E501
"""Study: when several early (leading) signals line up within a few bars, does the price go up afterwards?

The idea being tested: volume up, MACD crossing up, a breakout, and so on each happen before a move; when at least 3 of them are true within a short window,
that is a stronger sign than any alone. Six bullish conditions are computed on daily bars of every liquid NSE stock since late 2019:
  volume    the bar closes up on at least 1.5x its 20-day average volume
  macd      MACD(12,26,9) crosses above its signal line
  breakout  the close is above the highest high of the previous 20 bars
  rsi       RSI(14) crosses above 50
  reclaim   the close crosses above the 50-day average
  ibtrend   an inside-bar breakout with an uptrend (the one candlestick pattern that beat a random stock, scripts/study_candle_patterns.py)
A condition counts as true for the `window` bars after it fires. A signal is the first bar on which `min_count` distinct conditions are true together.
Everything is known at that bar's close; the return runs from it: close(+H sessions) / close - 1 less the median stock that day. `edge` is the mean against
a random stock (which drifts up); `beat %` is the share that beat the median stock (50 = no edge). A window that crosses a split or bonus is dropped.
usage: study_confluence.py [--db URL] [--horizon 10] [--min-turnover-cr 5]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--horizon", type=int, default=10)
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
ap.add_argument(
    "--check",
    help="print the 3+ aligned (5-bar window) signal dates and conditions for one symbol, to compare with the chart",
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
HZ = a.horizon

with psycopg.connect(a.db) as conn:
    symbols = dict(
        conn.execute(
            "SELECT instrument_id, symbol FROM instrument WHERE asset_class='equity'"
        ).fetchall()
    )
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, high::float8, low::float8, close::float8, volume::float8"
        " FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= '2019-09-01' ORDER BY instrument_id, ts, dataset_version DESC"
    ).fetchall()
    splits = conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ).fetchall()

df = pd.DataFrame(rows, columns=["iid", "d", "h", "l", "c", "v"])
del rows


def mat(frame: pd.DataFrame, col: str) -> pd.DataFrame:
    return frame.pivot(index="d", columns="iid", values=col).sort_index()


H, L, C, V = (mat(df, k) for k in ("h", "l", "c", "v"))
del df
R = H - L
avg14 = R.shift(1).rolling(14, min_periods=14).mean()
sma50 = C.rolling(50, min_periods=50).mean()

volume = (V >= 1.5 * V.shift(1).rolling(20, min_periods=15).mean()) & (C > C.shift(1))
ema12, ema26 = C.ewm(span=12, adjust=False).mean(), C.ewm(span=26, adjust=False).mean()
macd = ema12 - ema26
signal = macd.ewm(span=9, adjust=False).mean()
macd_cross = (macd > signal) & (macd.shift(1) <= signal.shift(1))
breakout = C > H.shift(1).rolling(20, min_periods=20).max()
d = C.diff()
rs = (
    d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    / (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
)
rsi = 100 - 100 / (1 + rs)
rsi_up = (rsi > 50) & (rsi.shift(1) <= 50)
reclaim = (C > sma50) & (C.shift(1) <= sma50.shift(1))

ins = (H < H.shift(1)) & (L > L.shift(1))
iv, rr = ins.to_numpy(), R.fillna(0).to_numpy()
rv, mv = np.zeros(iv.shape, dtype=int), np.zeros(iv.shape)
for t in range(1, len(C.index)):
    rv[t] = np.where(iv[t], rv[t - 1] + 1, 0)
    mv[t] = np.where(iv[t], np.maximum(mv[t - 1], rr[t]), 0.0)
run, runmax = (
    pd.DataFrame(rv, index=C.index, columns=C.columns),
    pd.DataFrame(mv, index=C.index, columns=C.columns),
)
mh = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
ml = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
for k in range(1, 40):
    sel = run.shift(1) == k
    mh, ml = mh.where(~sel, H.shift(k + 1)), ml.where(~sel, L.shift(k + 1))
mr = mh - ml
ib_setup = (run.shift(1) >= 1) & (mr >= avg14) & (runmax.shift(1) <= 0.6 * mr)
uptrend = (C.shift(1) > sma50) & (sma50 > sma50.shift(10))
ibtrend = ib_setup & (C > mh) & uptrend

CONDS = {
    "volume": volume,
    "macd": macd_cross,
    "breakout": breakout,
    "rsi": rsi_up,
    "reclaim": reclaim,
    "ibtrend": ibtrend,
}
CONDS = {k: v.fillna(False).astype(bool) for k, v in CONDS.items()}

if a.check:
    iid = next(i for i, s_ in symbols.items() if s_ == a.check and i in C.columns)
    rec = {k: v[iid].astype(float).rolling(5, min_periods=1).max() for k, v in CONDS.items()}
    cnt = sum(rec.values())
    for day in C.index[((cnt >= 3) & (cnt.shift(1) < 3)).to_numpy()]:
        print(day, "+".join(k for k in CONDS if rec[k][day] == 1))
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
    f"horizon {HZ} sessions, turnover >= {a.min_turnover_cr} Cr. A random stock: beats the median stock {100 * (base > 0).mean():.1f}%, mean {100 * bm:+.2f}%.\n"
)


def report(name: str, m: pd.DataFrame) -> None:
    e = ex.where(m & liquid).stack().dropna()
    if len(e) < 30:
        print(f"{name:<44}{len(e):>8}")
        return
    pw = (e - bm).groupby(level=0).mean()
    t = pw.mean() / (pw.std() / np.sqrt(len(pw))) if len(pw) > 5 and pw.std() > 0 else float("nan")
    print(
        f"{name:<44}{len(e):>8,}{100 * (e > 0).mean():>9.1f}{100 * e.median():>10.2f}{100 * e.mean():>9.2f}{100 * (e.mean() - bm):>8.2f}{t:>9.2f}"
    )


def header(title: str) -> None:
    print(f"--- {title}")
    print(
        f"{'':<44}{'signals':>8}{'beat %':>9}{'median %':>10}{'mean %':>9}{'edge %':>8}{'t(edge)':>9}"
    )


header("each condition alone (the bar it fires on)")
for k, v in CONDS.items():
    report(k, v)
print()

for window in (3, 5, 10):
    recent = {k: v.astype(float).rolling(window, min_periods=1).max() for k, v in CONDS.items()}
    count = sum(recent.values())
    header(
        f"{window}-bar window: the first bar on which at least N distinct conditions are true together"
    )
    for need in (2, 3, 4):
        trig = (count >= need) & (count.shift(1) < need)
        report(f"at least {need} of 6", trig)
    print()

# which conditions drive it: at 3+ in a 5-bar window, how does it split by which ones are present
recent5 = {k: v.astype(float).rolling(5, min_periods=1).max() for k, v in CONDS.items()}
count5 = sum(recent5.values())
trig3 = (count5 >= 3) & (count5.shift(1) < 3)
header("5-bar window, 3+ aligned: split by whether each condition is among them")
for k in CONDS:
    report(f"{k} present", trig3 & (recent5[k] == 1))
    report(f"{k} absent", trig3 & (recent5[k] == 0))
print()
header("5-bar window, 3+ aligned: by the count reached on that bar")
for need in (3, 4, 5, 6):
    report(f"exactly {need}", (count5 == need) & (count5.shift(1) < 3))
