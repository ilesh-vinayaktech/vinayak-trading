# ruff: noqa: E501
"""EMA 9/21 cross + MACD turn, with stop, 3:1 target and signal exits (2026-11-19). RESEARCH ONLY. FROZEN BEFORE THE FIRST RUN; nothing below was tuned.

Owner's rule. ENTRY (signal at the close of T): EMA(9) crossed above EMA(21) AND MACD(12,26,9) crossed above its signal line, each within the last 3 sessions (T included), both still up at T; first such day with none in the 10 days before.
Buy at the OPEN of T+1. RISK R = 2 x ATR14(T) (a stop is needed for a 3:1 ratio; the owner gave none). Exits, first that happens (daily bars; a day that touches both stop and target counts as the STOP):
  stop      low <= entry - R (filled at the stop, or at the open if it gapped below)
  target    high >= entry + 3R (filled at the target, or at the open if it gapped above)
  signal    at a close: MACD back under its signal, or EMA9 back under EMA21, or a distribution day (close down AND volume >= 1.5 x its 20-day mean) -> sell at the next open
  time      60 sessions -> sell at that close.
"Any other 3 signals" is not a separate exit: any single one of the reversal signals above already exits, so a 3-of-N rule can only be slower.
Universe: liquid stocks (20-day turnover >= Rs 5 crore), no split/bonus within 70 sessions before or 60 after. Excess = trade return minus the equal-weight liquid index over the same sessions (close T to exit day).
Cost: 0.25% round trip (primary), 0.5% shown. Data: bars strictly before 2025-01-01 (config/research_holdout.json); the holdout is not read.
SUCCESS RULE (fixed now): net mean excess per entry-date > 0 with t over dates > 1.96 AND positive in at least 4 of the 5 years 2020-2024; fewer than 300 trades = INCONCLUSIVE; else FAIL. Variants (1 and 3 ATR stops, no stop/target) are printed and cannot rescue a FAIL.
usage: study_ema_macd_exit.py [--db URL] [--symbol HONASA --through YYYY-MM-DD]   (--symbol is a worked example on one stock, not evidence)"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from algo.market import rise_odds as ro

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--symbol")
ap.add_argument("--through")
ap.add_argument(
    "--simple",
    action="store_true",
    help="owner's simple version: exit only when MACD or EMA turns down (no volume exit, no stop/target); with --all every stock, not just liquid ones",
)
ap.add_argument("--all", action="store_true")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
END = json.loads(
    (Path(__file__).resolve().parents[1] / "config/research_holdout.json").read_text()
)["holdout_start"]
if a.through:
    END = (pd.Timestamp(a.through) + pd.Timedelta(days=1)).date().isoformat()
with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        " FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= '2019-09-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC", (END,)
    ).fetchall()  # fmt: skip
    splits = ro.load_splits(conn)
    sym = {int(i): s for i, s in conn.execute("SELECT instrument_id, symbol FROM instrument")}
d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
O, H, L, C, V = (  # noqa: E741
    d.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c", "v")
)
T, S = C.shape
idx = np.array(C.index, dtype="datetime64[D]")
liq = ((C * V).rolling(20, min_periods=15).mean() / 1e7) >= 5.0
bad = pd.DataFrame(False, index=C.index, columns=C.columns)
pos = {int(c): k for k, c in enumerate(C.columns)}
for iid, ex in splits:
    if iid in pos:
        i = int(np.searchsorted(idx, np.datetime64(ex)))
        bad.iloc[max(0, i - 70) : min(T, i + 61), pos[iid]] = True
tradable = ((C.notna() if a.all else liq) & ~bad & C.notna()).to_numpy()

ema = lambda x, n: x.ewm(span=n, adjust=False).mean()  # noqa: E731
e9, e21 = ema(C, 9), ema(C, 21)
macd = ema(C, 12) - ema(C, 26)
sig = macd.ewm(span=9, adjust=False).mean()
pc = C.shift(1)
atr = np.maximum(H - L, np.maximum((H - pc).abs(), (L - pc).abs())).rolling(14).mean()
up_e, up_m = e9 > e21, macd > sig
x_e, x_m = up_e & ~up_e.shift(1, fill_value=False), up_m & ~up_m.shift(1, fill_value=False)
rec = lambda f: f.astype(float).rolling(3, min_periods=1).max() == 1  # noqa: E731
sigmask = (rec(x_e) & rec(x_m) & up_e & up_m).to_numpy() & tradable
prior = (
    pd.DataFrame(sigmask)
    .shift(1, fill_value=False)
    .rolling(10, min_periods=1)
    .max()
    .astype(bool)
    .to_numpy()
)
entry = sigmask & ~prior
dist = ((C < pc) & (V >= 1.5 * V.shift(1).rolling(20, min_periods=15).mean())).to_numpy()
rev = (~up_m | ~up_e).to_numpy() | (False if a.simple else dist)
o, h, lo, c, at = (x.to_numpy(float) for x in (O, H, L, C, atr))
ret1 = C.pct_change().where(liq)
lvl = np.cumsum(np.log1p(ret1.mean(axis=1).fillna(0).to_numpy()))
MAXH = 60


def simulate(
    t: int, s: int, k_stop: float, rr: float, use_bracket: bool
) -> tuple[int, float, str] | None:
    if t + 1 >= T or not np.isfinite(at[t, s]) or not np.isfinite(o[t + 1, s]):
        return None
    ent = o[t + 1, s]
    risk = k_stop * at[t, s]
    stop, tgt = ent - risk, ent + rr * risk
    for j in range(t + 1, min(t + 1 + MAXH, T)):
        if not np.isfinite(c[j, s]):
            return None
        if use_bracket:
            if j > t + 1 and o[j, s] <= stop:
                return j, o[j, s] / ent - 1, "stop"
            if lo[j, s] <= stop:
                return j, stop / ent - 1, "stop"
            if j > t + 1 and o[j, s] >= tgt:
                return j, o[j, s] / ent - 1, "target"
            if h[j, s] >= tgt:
                return j, tgt / ent - 1, "target"
        if rev[j, s] and j + 1 < T and np.isfinite(o[j + 1, s]):
            return j + 1, o[j + 1, s] / ent - 1, "signal"
    j = min(t + MAXH, T - 1)
    return (
        (j, c[j, s] / ent - 1, "time") if j == t + MAXH else None
    )  # a trade still open at the end of the data is dropped


def run(k_stop: float, rr: float, bracket: bool) -> pd.DataFrame:
    out = []
    for t, s in zip(*np.nonzero(entry), strict=True):
        r = simulate(int(t), int(s), k_stop, rr, bracket)
        if r:
            j, ret, why = r
            out.append((int(t), int(s), j, ret, ret - np.expm1(lvl[j] - lvl[t]), why))
    return pd.DataFrame(out, columns=["t", "s", "j", "ret", "ex", "why"])


def tstat(x: pd.Series) -> float:
    return (
        float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))
        if len(x) > 5 and x.std(ddof=1) > 0
        else float("nan")
    )


def report(title: str, tr: pd.DataFrame, primary: bool = False) -> None:
    tr = tr.assign(year=pd.DatetimeIndex(idx[tr.t]).year, days=tr.j - tr.t)
    print(
        f"\n##### {title}: {len(tr):,} trades; exits "
        + ", ".join(f"{k} {100 * v:.0f}%" for k, v in tr.why.value_counts(normalize=True).items())
    )
    print(
        f"  {'year':<7}{'n':>6}{'win %':>7}{'mean %':>8}{'avg win':>9}{'avg loss':>9}{'days':>6}{'excess %':>10}{'net .25%':>10}{'net .5%':>9}{'t(dates)':>9}"
    )
    yrs = {str(y): tr[tr.year == y] for y in range(2019, 2025)} | {"ALL": tr}
    pos_years = 0
    for name, g in yrs.items():
        if len(g) < 20:
            print(f"  {name:<7}{len(g):>6}")
            continue
        w, ls = g.ret[g.ret > 0], g.ret[g.ret <= 0]
        net = g.ex - 0.0025
        t_ = tstat(net.groupby(g.t).mean())
        if name in ("2020", "2021", "2022", "2023", "2024") and net.mean() > 0:
            pos_years += 1
        print(
            f"  {name:<7}{len(g):>6}{100 * (g.ret > 0).mean():>7.1f}{100 * g.ret.mean():>8.2f}{100 * w.mean():>9.2f}{100 * ls.mean():>9.2f}{g.days.mean():>6.1f}{100 * g.ex.mean():>10.2f}{100 * net.mean():>10.2f}{100 * (g.ex - 0.005).mean():>9.2f}{t_:>9.1f}"
        )
    if primary:
        net = tr.ex - 0.0025
        t_all = tstat(net.groupby(tr.t).mean())
        verdict = (
            "INCONCLUSIVE"
            if len(tr) < 300
            else ("PASS" if net.mean() > 0 and t_all > 1.96 and pos_years >= 4 else "FAIL")
        )
        print(
            f"  VERDICT (frozen rule): {verdict}  [net excess {100 * net.mean():+.2f}%, t {t_all:.1f}, positive years {pos_years}/5]"
        )


if a.symbol:
    s = next(k for k, v in pos.items() if sym[k] == a.symbol)
    col = pos[s]
    for t in np.nonzero(entry[:, col])[0][-4:]:
        r = simulate(int(t), col, 2.0, 3.0, True)
        print(
            f"{a.symbol} signal {idx[t]}, buy open {o[t + 1, col]:.2f}, stop {o[t + 1, col] - 2 * at[t, col]:.2f}, target {o[t + 1, col] + 6 * at[t, col]:.2f} ->",
            f"exit {idx[r[0]]} {r[2]} {100 * r[1]:+.2f}%" if r else "still open / no data",
        )
    sys.exit()
if a.simple:
    report(
        f"SIMPLE: buy on the cross, sell when MACD or EMA turns down ({'every stock' if a.all else 'liquid stocks'})",
        run(2.0, 3.0, False),
        primary=True,
    )
    sys.exit()
print(f"panel {T} sessions x {S} stocks, {int(entry.sum()):,} entry signals")
report("PRIMARY: 2 ATR stop, 3:1 target, signal exits", run(2.0, 3.0, True), primary=True)
report("variant: 1 ATR stop, 3:1", run(1.0, 3.0, True))
report("variant: 3 ATR stop, 3:1", run(3.0, 3.0, True))
report("variant: no stop/target, signal exits only", run(2.0, 3.0, False))
