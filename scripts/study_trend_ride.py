# ruff: noqa: E501
"""Trend ride (2026-11-19): judged as a trend-following rule, NOT as a 20-session outperformance ranking. RESEARCH ONLY. FROZEN BEFORE THE FIRST RUN; nothing below was tuned.

Rule = src/algo/strategies/trend_ride.py v1 (default 20-session breakout, 3 x ATR chandelier), reimplemented on pandas panels:
  state UP : close > EMA50 and EMA50 > 1.005 x EMA50 ten sessions ago.   ENTRY (signal at close T): UP, close above the highest close of the previous 20 sessions, close above the stop; buy the OPEN of T+1.
  stop     : highest high of the last 22 sessions - 3 x ATR14 (Wilder), recomputed every day.   EXIT (decided at a close): close <= stop or close < EMA50 -> sell the next open.
  Universe : liquid stocks (20-day turnover >= Rs 5 crore). Data: Kite adjusted bars (no split mask needed) strictly before the holdout (config/research_holdout.json).
Two views: (1) TRADES, every signal taken, no slot limit: win %, average win/loss, expectancy in R (R = distance from the signal-day close to the stop), net of the repo's real round-trip cost.
(2) PORTFOLIO, max 10 equal slots (1/10 each), tightest stop first, cash when idle, cost charged at entry: return, max drawdown, Calmar (return / drawdown), time invested, against the equal-weight liquid index (buy and hold), 2020-2024 (2019-09..12 is warm-up).
SUCCESS RULE (fixed now): PASS needs ALL of: >= 300 trades; mean NET R per trade > 0 with t over entry dates > 1.96; net R positive in >= 4 of the 5 years 2020-2024; portfolio Calmar 2020-2024 above the index's Calmar AND portfolio max drawdown shallower than the index's.
Fewer than 300 trades = INCONCLUSIVE; anything else FAIL. Variants (55-session breakout, 2 and 4 ATR) are printed and cannot rescue a FAIL.
usage: study_trend_ride.py [--db URL]"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, flat_cost  # noqa: E402,I001

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
END = json.loads(
    (Path(__file__).resolve().parents[1] / "config/research_holdout.json").read_text()
)["holdout_start"]
with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-09-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC", (END,)
    ).fetchall()  # fmt: skip
d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
O, H, L, C, V = (  # noqa: E741
    d.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c", "v")
)
T, S = C.shape
idx = pd.DatetimeIndex(C.index)
liq = ((C * V).rolling(20, min_periods=15).mean() / 1e7) >= 5.0
ready = C.notna().cumsum() >= 80
ema50 = C.ewm(span=50, adjust=False).mean()
pc = C.shift(1)
tr = np.maximum(H - L, np.maximum((H - pc).abs(), (L - pc).abs()))
atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
top = H.rolling(22).max()
up = (C > ema50) & (ema50 > ema50.shift(10) * 1.005)
index_ret = C.pct_change().where(liq).mean(axis=1).fillna(0).to_numpy()
COST = flat_cost()
N = 10
o, c = O.to_numpy(float), C.to_numpy(float)


def masks(breakout: int, k: float):
    stop = top - k * atr
    sig = (up & (C > pc.rolling(breakout).max()) & (C > stop) & liq & ready).to_numpy()
    out = ((C <= stop) | (C < ema50)).to_numpy()
    risk = ((C - stop) / C).to_numpy(float)
    return sig, out, risk


def trades(sig, out, risk) -> pd.DataFrame:
    rec = []
    for s in range(S):
        ex_all = np.flatnonzero(out[:, s])
        t = 0
        while t < T - 2:
            if not sig[t, s]:
                t += 1
                continue
            e = t + 1
            nxt = ex_all[(ex_all >= e) & (ex_all < T - 1)]
            if nxt.size == 0:
                break  # still open at the end of the data: dropped
            if not np.isfinite(o[e, s]):
                t += 1
                continue
            x = int(nxt[0]) + 1  # sell at the open after the exit close
            if np.isfinite(o[x, s]):
                r = o[x, s] / o[e, s] - 1
                rec.append((t, s, x, r, (r - COST) / risk[t, s], x - e))
            t = x
    return pd.DataFrame(rec, columns=["t", "s", "x", "ret", "netR", "days"])


def portfolio(sig, out, risk) -> tuple[np.ndarray, np.ndarray]:
    ret, invested = np.zeros(T), np.zeros(T)
    held: set[int] = set()
    sell: set[int] = set()
    buy: list[int] = []
    for t in range(1, T):
        r = 0.0
        for (
            s
        ) in held:  # held at the close of t-1; a name decided out last night leaves at today's open
            x = (o[t, s] if s in sell else c[t, s]) / c[t - 1, s] - 1
            r += x if np.isfinite(x) else 0.0
        held -= sell
        for s in buy:  # bought at today's open
            x = c[t, s] / o[t, s] - 1
            r += (x if np.isfinite(x) else 0.0) - COST
            held.add(s)
        ret[t], invested[t] = r / N, len(held) / N
        sell = {s for s in held if out[t, s]}
        cand = np.flatnonzero(sig[t])
        cand = [int(s) for s in cand[np.argsort(risk[t, cand], kind="stable")] if s not in held]
        free = N - (len(held) - len(sell))
        buy = [s for s in cand if t + 1 < T and np.isfinite(o[t + 1, s])][: max(free, 0)]
    return ret, invested


def curve_stats(r: np.ndarray) -> tuple[float, float, float]:
    eq = np.cumprod(1 + r)
    dd = float((eq / np.maximum.accumulate(eq) - 1).min())
    cagr = float(eq[-1] ** (252 / max(len(r), 1)) - 1)
    return cagr, dd, cagr / abs(dd) if dd < 0 else float("nan")


def tstat(x: pd.Series) -> float:
    return (
        float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))
        if len(x) > 5 and x.std(ddof=1) > 0
        else float("nan")
    )


def report(title: str, breakout: int, k: float, primary: bool = False) -> None:
    sig, out, risk = masks(breakout, k)
    tr = trades(sig, out, risk)
    tr["year"] = idx[tr.t.to_numpy()].year
    print(f"\n##### {title}: {len(tr):,} trades (cost {100 * COST:.2f}% a round trip)")
    print(
        f"  {'year':<6}{'n':>6}{'win %':>7}{'avg win %':>10}{'avg loss %':>11}{'days':>6}{'mean %':>8}{'net R':>7}{'t(dates)':>9}"
    )
    pos = 0
    for name, g in (
        {str(y): tr[tr.year == y] for y in range(2020, 2025)} | {"ALL": tr[tr.year >= 2020]}
    ).items():
        if len(g) < 20:
            print(f"  {name:<6}{len(g):>6}")
            continue
        w, ls = g.ret[g.ret > 0], g.ret[g.ret <= 0]
        if name != "ALL" and g.netR.mean() > 0:
            pos += 1
        print(
            f"  {name:<6}{len(g):>6}{100 * (g.ret > 0).mean():>7.1f}{100 * w.mean():>10.2f}{100 * ls.mean():>11.2f}{g.days.mean():>6.1f}{100 * g.ret.mean():>8.2f}{g.netR.mean():>7.2f}{tstat(g.groupby('t').netR.mean()):>9.1f}"
        )
    ret, inv = portfolio(sig, out, risk)
    keep = np.asarray(idx.year >= 2020)
    print(f"  portfolio (max {N} slots) vs equal-weight index, 2020-2024:")
    print(f"  {'':<8}{'CAGR %':>8}{'max DD %':>10}{'Calmar':>8}{'invested %':>12}")
    sc, sd, sk = curve_stats(ret[keep])
    ic, idd, ik = curve_stats(index_ret[keep])
    print(
        f"  {'strategy':<8}{100 * sc:>8.1f}{100 * sd:>10.1f}{sk:>8.2f}{100 * inv[keep].mean():>12.0f}"
    )
    print(f"  {'index':<8}{100 * ic:>8.1f}{100 * idd:>10.1f}{ik:>8.2f}{100:>12.0f}")
    for y in range(2020, 2025):
        m = np.asarray(idx.year == y)
        print(
            f"    {y}: strategy {100 * (np.prod(1 + ret[m]) - 1):+6.1f}%  (DD {100 * curve_stats(ret[m])[1]:6.1f}%)   index {100 * (np.prod(1 + index_ret[m]) - 1):+6.1f}%  (DD {100 * curve_stats(index_ret[m])[1]:6.1f}%)"
        )
    if primary:
        g = tr[tr.year >= 2020]
        t_all = tstat(g.groupby("t").netR.mean())
        verdict = (
            "INCONCLUSIVE"
            if len(g) < 300
            else "PASS"
            if g.netR.mean() > 0 and t_all > 1.96 and pos >= 4 and sk > ik and sd > idd
            else "FAIL"
        )
        print(
            f"  VERDICT (frozen rule): {verdict}  [net R {g.netR.mean():+.2f}, t {t_all:.1f}, positive years {pos}/5, Calmar {sk:.2f} vs index {ik:.2f}, max DD {100 * sd:.1f}% vs {100 * idd:.1f}%]"
        )


print(f"panel {T} sessions x {S} stocks")
report("PRIMARY: 20-session breakout, 3 ATR chandelier", 20, 3.0, primary=True)
report("variant: 55-session breakout, 3 ATR", 55, 3.0)
report("variant: 20-session breakout, 2 ATR", 20, 2.0)
report("variant: 20-session breakout, 4 ATR", 20, 4.0)
