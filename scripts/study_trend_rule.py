# ruff: noqa: E501
"""Study: the owner's trend rule, tested the way a trend rule is meant to be used.

Rule: EMA(9) above EMA(21), MACD(12,26,9) above its signal line, and RSI above 50 (tried with the 14-period RSI and the 50-period RSI of the chart's legend). Entry at the close of the first
day all three agree (none of them was in agreement on every one of the 10 days before). Two ways of judging it:
  A  fixed holding periods of 5, 10, 20 and 40 sessions: the return less the median liquid stock's over the same window (as the rise-odds studies do);
  B  as a trend trade: hold until EMA(9) closes back under EMA(21), at most 60 sessions: the trade's return, its win rate, average win against average loss, how long it lasted, and the
     return less the median liquid stock's over the same window. Trend rules usually lose often and win big, which a hit rate hides, so B shows the payoff.
Tuned on 2019-2023, judged on 2024 onward, by year as well; every figure is for liquid NSE stocks (20-day turnover of Rs 5 crore or more). A cost line is shown for a 0.5% round trip.
usage: study_trend_rule.py [--db URL]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, flat_cost, use_kite_panel  # noqa: E402,I001

from algo.market import rise_odds as ro

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

use_kite_panel(ro)  # Kite adjusted bars, not the NSE raw panel + split mask
with psycopg.connect(a.db) as conn:
    last = conn.execute(
        f"SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM {BARS} WHERE source='kite'"
    ).fetchone()[0]
    p = ro.load_panel(conn, ro.HISTORY_FROM, last)
    splits = ro.load_splits(conn)
C = p.close
T, S = C.shape
idx = np.array(C.index, dtype="datetime64[D]")
liq = ro.liquid(p)
bad = ro._split_mask(
    p, splits, 70, 60
)  # a trade may run 60 sessions: no split inside or just before
tradable = (liq & ~bad & C.notna()).to_numpy()

ema9, ema21 = C.ewm(span=9, adjust=False).mean(), C.ewm(span=21, adjust=False).mean()
macd = C.ewm(span=12, adjust=False).mean() - C.ewm(span=26, adjust=False).mean()
macd_up = macd > macd.ewm(span=9, adjust=False).mean()


def wilder_rsi(n: int) -> pd.DataFrame:
    d = C.diff()
    return 100 - 100 / (
        1
        + d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
        / (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    )


ema_up = ema9 > ema21
cross_dn = (
    (ema9 < ema21) & (ema9.shift(1) >= ema21.shift(1))
).to_numpy()  # EMA(9) closes back under EMA(21)

# the market over a window of any length (a trend trade lasts as long as it lasts): an equal-weight index of the liquid stocks built from each day's MEAN return (compounding the daily MEDIAN is biased
# low and flatters any rule: a first version of this script did that and showed the market down 72%), so a trade is compared with it over exactly its own days
ret1 = C.pct_change().where(liq)
mkt_level = np.cumsum(
    np.log1p(ret1.mean(axis=1).fillna(0).to_numpy())
)  # the log level of the equal-weight index at each close


def window_mkt(t0: np.ndarray, t1: np.ndarray) -> np.ndarray:
    return np.expm1(mkt_level[t1] - mkt_level[t0])


rowno = np.broadcast_to(np.arange(T)[:, None], (T, S))
big = T + 10_000
nxt_dn = np.minimum.accumulate(np.where(cross_dn, rowno, big)[::-1], axis=0)[
    ::-1
]  # for each day the first same-or-later day EMA(9) crosses under EMA(21)

Cv = C.to_numpy()
oos = idx >= np.datetime64("2024-01-01")
years = pd.DatetimeIndex(idx).year.to_numpy()
HORIZONS = (5, 10, 20, 40)
fwd = {h: (C.shift(-h) / C - 1).to_numpy() for h in HORIZONS}
ok_h = liq & ~bad
mkt_fwd = {
    h: (C.shift(-h) / C - 1).where(ok_h).median(axis=1).to_numpy() for h in HORIZONS
}  # the median liquid stock's return over the same h sessions, day by day (as the rise-odds studies do)


def tstat(by_day: pd.Series) -> float:
    return (
        float(by_day.mean() / (by_day.std(ddof=1) / np.sqrt(len(by_day))))
        if len(by_day) > 5 and by_day.std(ddof=1) > 0
        else float("nan")
    )


def judge(title: str, entry: np.ndarray) -> None:
    ok = entry & tradable
    first = (
        ok
        & ~pd.DataFrame(ok)
        .shift(1, fill_value=False)
        .rolling(10, min_periods=1)
        .max()
        .astype(bool)
        .to_numpy()
    )  # first day of each run: none in the 10 days before
    print(
        f"\n##### {title}: {int(first.sum()):,} entries ({int((first & ~oos[:, None]).sum()):,} in 2019-23, {int((first & oos[:, None]).sum()):,} from 2024)"
    )
    print(
        "  A. fixed holding periods: return less the median liquid stock's over the same sessions"
    )
    print(
        f"     {'':<8}{'period':<10}{'trades':>8}{'beat the median %':>20}{'mean excess %':>15}{'mean return %':>15}{'t (by day)':>12}"
    )
    for h in HORIZONS:
        for name, per in (("2019-23", ~oos), ("2024+", oos)):
            m = first & per[:, None] & (np.arange(T)[:, None] < T - h)
            d, s_ = np.nonzero(m)
            r = fwd[h][d, s_]
            good = ~np.isnan(r)
            d, r = d[good], r[good]
            ex = r - mkt_fwd[h][d]
            print(
                f"     {h:>3} days {name:<10}{len(r):>8,}{100 * (ex > 0).mean():>19.1f}%{100 * ex.mean():>15.2f}{100 * r.mean():>15.2f}{tstat(pd.Series(ex).groupby(d).mean()):>12.1f}"
            )
    print("  B. as a trend trade: hold until EMA(9) closes under EMA(21), at most 60 sessions")
    print(
        f"     {'period':<9}{'trades':>8}{'win %':>8}{'mean %':>9}{'median %':>10}{'avg win %':>11}{'avg loss %':>12}{'days':>7}{'excess vs the index %':>26}{'t':>7}{'  after real cost %':>20}"
    )
    d, s_ = np.nonzero(first)
    cross_row = nxt_dn[np.minimum(d + 1, T - 1), s_]
    ex_row = np.minimum(cross_row, d + 60)
    done = (
        ex_row < T
    )  # a trade counts once it has ended (an exit cross or 60 sessions) inside the data
    d, s_, ex_row = d[done], s_[done], ex_row[done]
    ret = Cv[ex_row, s_] / Cv[d, s_] - 1
    good = ~np.isnan(ret)
    d, s_, ex_row, ret = d[good], s_[good], ex_row[good], ret[good]
    excess = ret - window_mkt(d, ex_row)
    for name, per in (
        ("2019-23", ~oos[d]),
        ("2024+", oos[d]),
        ("2024", years[d] == 2024),
        ("2025", years[d] == 2025),
        ("2026", years[d] == 2026),
    ):
        r, e, dd = ret[per], excess[per], d[per]
        if len(r) < 30:
            print(f"     {name:<9}{len(r):>8}")
            continue
        wins, loss = r[r > 0], r[r <= 0]
        print(
            f"     {name:<9}{len(r):>8,}{100 * (r > 0).mean():>8.1f}{100 * r.mean():>9.2f}{100 * np.median(r):>10.2f}{100 * wins.mean():>11.2f}{100 * loss.mean():>12.2f}{np.mean(ex_row[per] - dd):>7.1f}{100 * e.mean():>26.2f}{tstat(pd.Series(e).groupby(dd).mean()):>7.1f}{100 * (r.mean() - flat_cost()):>20.2f}"
        )


for rsi_len in (14, 50):
    rsi = wilder_rsi(rsi_len)
    judge(
        f"EMA 9 over 21 + MACD over signal + RSI({rsi_len}) over 50",
        (ema_up & macd_up & (rsi > 50)).to_numpy(),
    )

# the same three, but required to have CROSSED within the last 5 days (the wording 'cross'), RSI(14)
rsi14 = wilder_rsi(14)


def recent(f: pd.DataFrame) -> pd.DataFrame:
    return f.astype(float).rolling(5, min_periods=1).max() == 1


crossed = (
    recent((ema9 > ema21) & (ema9.shift(1) <= ema21.shift(1)))
    & recent(macd_up & ~macd_up.shift(1, fill_value=False).astype(bool))
    & recent((rsi14 > 50) & (rsi14.shift(1) <= 50))
)
judge(
    "each of EMA 9/21, MACD and RSI(14) 50 CROSSED up within the last 5 days",
    (crossed & ema_up & macd_up & (rsi14 > 50)).to_numpy(),
)
print(
    f"\nreference, the equal-weight index of liquid stocks: 2019-23 {100 * np.expm1(mkt_level[np.nonzero(oos)[0][0]] - mkt_level[0]):+.1f}%, from 2024 {100 * np.expm1(mkt_level[-1] - mkt_level[np.nonzero(oos)[0][0]]):+.1f}% in total"
)
