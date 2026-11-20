# ruff: noqa: E501
"""Signal freshness study (2026-11-19). RESEARCH ONLY. FROZEN BEFORE THE FIRST RUN; nothing below was tuned.

Owner's idea: a stock that just fired an early-buy event deserves the highest score, and the score should fall as the days pass and the signal fades.
Question: for each event that held up in earlier studies (plus the owner's own recipe), how does the edge change with the AGE of the event?
Age a = sessions since the event day e; the measured return runs from the close of e+a to the close of e+a+H (H = --horizon, default 10), less the median liquid stock's return over the same days.
Events (all causal, each known at its bar's close; first day of a streak = not true on any of the 10 bars before):
  high52      close above the previous 252 bars' highest high
  squeeze     close above the upper Bollinger band right after a squeeze (bandwidth < 0.8x its 120-bar mean)
  base_surge  40-bar range (high/low-1) <= 30%, then volume >= 2x its 20-day average on an up bar, delivery >= 50% of volume
  owner       RSI(14) at or under its OWN 20th percentile of the last 1250 bars (min 500) on some bar of the last 10, AND a MACD(12,26,9) cross up on some bar of the last 10, AND today a 20-bar breakout on >= 1.5x volume
              (data starts 2019-09, so the own-history percentile exists only from about 2021-09: this row has a shorter in-sample)
Verdict rule (fixed now): an event HAS an edge if at age 0 the IS and OOS edges are both > 0 and the OOS day-level t >= 2 (fewer than 200 events in a part = INCONCLUSIVE). It FADES if its edge at age 10 is below half its age-0 edge in OOS.
Judging: IS = bars through 2023, OOS = 2024 (never used to choose). Bars stop before config/research_holdout.json holdout_start (2025-01-01). Splits/bonuses dropped; liquid = 20-day mean turnover >= Rs 5 crore.
Edge is the mean excess return less a random liquid stock's; entry is the CLOSE of e+a (not a tradable price: next-open entry and costs come only after an event passes). 'beat' = share beating the median stock.
usage: study_signal_decay.py [--db URL] [--horizon 10]"""

import argparse
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
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
HZ, AGES = a.horizon, (0, 1, 2, 3, 5, 10)
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
H, L, C, V, DQ = (
    df.pivot(index="d", columns="iid", values=k).sort_index() for k in ("h", "l", "c", "v", "dq")
)
del df
T, S = C.shape
sma20 = C.rolling(20, min_periods=20).mean()


def crossed_up(x: pd.DataFrame, y: pd.DataFrame) -> pd.DataFrame:
    return (x > y) & (x.shift(1) <= y.shift(1))


def first(e: pd.DataFrame) -> pd.DataFrame:
    return e & ~e.shift(1, fill_value=False).astype(bool).rolling(10, min_periods=1).max().astype(
        bool
    )


def within(
    e: pd.DataFrame, n: int
) -> pd.DataFrame:  # true if e was true on any of the last n bars (today included)
    return e.astype(float).rolling(n, min_periods=1).max().astype(bool)


avgv = V.shift(1).rolling(20, min_periods=15).mean()
up_bar = C > C.shift(1)
vol_up = (V >= 1.5 * avgv) & up_bar
macd = C.ewm(span=12, adjust=False).mean() - C.ewm(span=26, adjust=False).mean()
macd_x = crossed_up(macd, macd.ewm(span=9, adjust=False).mean())
brk20 = C > H.shift(1).rolling(20, min_periods=20).max()
dl = C.diff()
rsi = 100 - 100 / (
    1
    + dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
)
rsi_low = rsi <= rsi.rolling(1250, min_periods=500).quantile(0.2)
sd20 = C.rolling(20, min_periods=20).std()
bw = 4 * sd20 / sma20
base_rng = (
    H.shift(1).rolling(40, min_periods=40).max() / L.shift(1).rolling(40, min_periods=40).min() - 1
)
dpct = DQ / V.where(V > 0) * 100

events: dict[str, pd.DataFrame] = {
    "high52": first(C > H.shift(1).rolling(252, min_periods=200).max()),
    "squeeze": first(
        (bw < 0.8 * bw.rolling(120, min_periods=60).mean()).shift(1, fill_value=False)
        & (C > sma20 + 2 * sd20)
    ),
    "base_surge": first((V >= 2 * avgv) & up_bar & (base_rng <= 0.30) & (dpct >= 50)),
    "owner": first(within(rsi_low, 10) & within(macd_x, 10) & brk20 & vol_up),
}

turnover = (C * V).rolling(20, min_periods=15).mean() / 1e7
fwd = C.shift(-HZ) / C - 1
bad = pd.DataFrame(False, index=C.index, columns=C.columns)
idx = C.index.values
for iid, ex_date in splits:
    if iid in bad.columns:
        i = int(np.searchsorted(idx, np.datetime64(ex_date)))
        bad.iloc[max(0, i - 25) : min(T, i + HZ + 1), bad.columns.get_loc(iid)] = True
liquid = ((turnover >= 5.0) & ~bad & fwd.notna()).to_numpy()
ex = fwd.sub(fwd.where(liquid).median(axis=1), axis=0).to_numpy()
day = np.nonzero(liquid)[0]
ex_f = ex[liquid]
oos = idx[day] >= SPLIT_DAY
bm_is, bm_oos = ex_f[~oos].mean(), ex_f[oos].mean()
print(
    f"horizon {HZ} sessions. Random liquid stock: edge base {100 * bm_is:+.2f}% IS, {100 * bm_oos:+.2f}% OOS; beats the median {100 * (ex_f[~oos] > 0).mean():.1f}% / {100 * (ex_f[oos] > 0).mean():.1f}%"
)


def stat(mask: np.ndarray, part: np.ndarray, bm: float) -> tuple[int, float, float, float]:
    sel = mask & part
    n = int(sel.sum())
    if n < 200:
        return n, float("nan"), float("nan"), float("nan")
    e = ex_f[sel] - bm
    d = day[sel]
    cnt = np.bincount(d, minlength=T)
    pw = (
        np.bincount(d, weights=e, minlength=T)[cnt > 0] / cnt[cnt > 0]
    )  # one number per day: events on the same day share the market's mood
    t = (
        pw.mean() / (pw.std(ddof=1) / np.sqrt(len(pw)))
        if len(pw) > 5 and pw.std(ddof=1) > 0
        else float("nan")
    )
    return n, 100 * (ex_f[sel] > 0).mean(), 100 * e.mean(), t


res: dict[
    str, dict[int, tuple[tuple[int, float, float, float], tuple[int, float, float, float]]]
] = {}
for name, ev in events.items():
    print(
        f"\n=== {name}: edge by age of the event (return from the close of e+age over {HZ} sessions)"
    )
    res[name] = {}
    for age in AGES:
        m = ev.shift(age, fill_value=False).to_numpy()[liquid]
        r1, r2 = stat(m, ~oos, bm_is), stat(m, oos, bm_oos)
        res[name][age] = (r1, r2)
        print(
            f"age {age:>2}  IS {r1[0]:>7,} beat {r1[1]:5.1f} edge {r1[2]:+5.2f} t {r1[3]:+5.1f} | OOS {r2[0]:>7,} beat {r2[1]:5.1f} edge {r2[2]:+5.2f} t {r2[3]:+5.1f}"
        )

print("\nVERDICT (rule frozen in the docstring)")
for name, r in res.items():
    (i0, o0), (_, o10) = r[0], r[10]
    if i0[0] < 200 or o0[0] < 200:
        print(f"{name:<11} INCONCLUSIVE (fewer than 200 events in a part)")
        continue
    has = i0[2] > 0 and o0[2] > 0 and o0[3] >= 2
    fades = bool(o10[2] < 0.5 * o0[2]) if has else None
    print(
        f"{name:<11} {'HAS AN EDGE' if has else 'NO EDGE'}"
        + (
            f"; {'FADES by age 10' if fades else 'does NOT fade by age 10'} (OOS {o0[2]:+.2f}% -> {o10[2]:+.2f}%)"
            if has
            else ""
        )
    )
