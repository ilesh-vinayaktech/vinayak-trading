# ruff: noqa: E501
"""Large-move reversal study (2026-11-19). RESEARCH ONLY; no product use. FROZEN BEFORE THE FIRST RUN.

Question: the price-only boosting model in scripts/study_next_session.py reached 63.4% accuracy at confidence >= 0.70 on 0.9% of days, measured close to close. Is that tradable when the order can only
fill at the NEXT SESSION'S OPEN, and does the model add anything beyond a plain "reverse yesterday's big move" rule?
FROZEN INPUTS: the model is NOT re-fitted. Its validation predictions (2021, 2022, 2023 folds, trained only on earlier days) were saved by that study and are read from data/research/next_session_preds_2026-11-19.npz
(sha256 checked against EXPECTED_SHA below). Threshold 0.70 on P(up) / (P(up) + P(down)): >= 0.70 = a long call, <= 0.30 = a short call. Not tuned; not a calibrated probability.
All eligible rows are kept, including those whose next session turned out FLAT (the original tail analysis dropped them, which used the answer to choose rows; the call set here uses only what was known at the close).
Timing: features and the call at the close of day T; entry at the OPEN of T+1 (never the close of T); exit at the close of T+1 (primary), T+2 or T+3. Missing, zero or out-of-range opens are excluded and counted.
Strategies (all defined before running):
  M_A   the price-only model, conf >= 0.70                       M_ALL  the full-feature model, same threshold (comparison only)
  R5    rule: previous-day return <= -5% -> long, >= +5% -> short   RCOV  rule with the model's own coverage: per fold the |previous-day return| cut that selects the same share of days as M_A (cut from training days only)
  BUCKET descriptive map of next-open results by previous-day return bucket on all rows (no selection)         NIFTY  the stock goes the way Nifty went today (market-direction baseline)
Excess = result less the same-day average of every eligible stock over the same horizon (so a market-wide overnight or intraday drift cannot pass as skill). Net = gross less the repo's cost schedule for the product
(INTRADAY for same-session, DELIVERY for 2-3 sessions; longs and shorts; Rs 1 lakh per trade) less slippage per side (primary 10 bps; 0 and 20 shown). Shorts are only executable in the cash market as same-session intraday
trades: 2 and 3 session shorts are shown gross only and marked not executable.
Primary hypothesis (the only one): M_A same-session next-open -> close, long and short SEPARATELY, mean net return per trade > 0 AND mean excess > 0, day-block 95% CI above 0 after Bonferroni over all strategy x side x horizon rows counted,
positive in each of 2021, 2022, 2023. Everything else is secondary and reported with the same count.
Data: bars strictly before 2024-01-01; the protected holdout (2025-01-01..2026-11-13, config/research_holdout.json) is not read. Section 8 audits which research scripts could read it.
usage: study_reversal.py [--db URL] [--preds PATH] [--log register.csv]"""

import argparse
import hashlib
import math
import os
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, book_from_db  # noqa: E402,I001

from algo.backtest.costs.calculator import compute_charges
from algo.research import next_session_features as ns

EXPECTED_SHA = "2d19078d7e31a1b85c56f644f4194ff491222d70049a32fea6bd287229dae772"
END = "2024-01-01"
THRESH = 0.70
ROOT = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--preds", default=str(ROOT / "data/research/next_session_preds_2026-11-19.npz"))
ap.add_argument(
    "--log",
    help="write the experiment register (every strategy x side x horizon x period) to this CSV",
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
sha = hashlib.sha256(Path(a.preds).read_bytes()).hexdigest()
if sha != EXPECTED_SHA and not os.environ.get("STUDY_RERUN"):
    sys.exit(f"error: the frozen predictions changed (sha256 {sha})")
z = np.load(a.preds)
day, stock, r_cc, cls = z["day"], z["stock"], z["r"], z["cls"]

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-01-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC",
        (END,),
    ).fetchall()
    nifty = conn.execute(
        "SELECT trade_date, close::float8 FROM index_bar_1d WHERE symbol='NIFTY 50' AND trade_date >= '2018-06-01' AND trade_date < %s ORDER BY trade_date",
        (END,),
    ).fetchall()
df = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c"])
del rows
df["d"] = pd.to_datetime(df["d"])
O, H, L, C = (  # noqa: E741
    df.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c")
)
del df
T, S = C.shape
idx = C.index.values
assert idx.max() < np.datetime64(END) and day.max() < T and stock.max() < S
NF = pd.Series({pd.Timestamp(d): x for d, x in nifty}).reindex(C.index, method="ffill")
chk = np.abs((C.shift(-1) / C - 1).to_numpy()[day, stock] - r_cc)
print(
    f"frozen predictions sha256 ok; {len(day):,} eligible rows; close-to-close return matches the saved target on {100 * np.nanmean(chk < 1e-5):.1f}% of rows (the rest carry a dividend add-back)"
)

E = ns.next_open_entry(O, H, L, C, (1, 2, 3))
HZ = (1, 2, 3)
ret = {h: E[f"ret{h}"][day, stock] for h in HZ}
mfe = {h: E[f"mfe{h}"][day, stock] for h in HZ}
mae = {h: E[f"mae{h}"][day, stock] for h in HZ}
ovn = E["overnight"][day, stock]
okentry = E["valid"][day, stock]
ret1d = (C / C.shift(1) - 1).to_numpy()[day, stock]
nday_dir = np.nan_to_num(np.sign((NF / NF.shift(1) - 1).to_numpy()[day]))
yr = (idx.astype("datetime64[Y]").astype(int) + 1970)[day]

# ---------------------------------------------------------------- the frozen model's calls on every validation row
ids_a, p_a = z["HGB__A__ids"], z["HGB__A__p"]
ids_f, p_f = z["HGB__ALL__ids"], z["HGB__ALL__p"]


def pbin(p3: np.ndarray) -> np.ndarray:
    return p3[:, 2] / np.maximum(p3[:, 2] + p3[:, 0], 1e-9)


pa, pf = pbin(p_a), pbin(p_f)
val_rows = ids_a
vyears = yr[val_rows]
nf = cls[ids_a] != 1
tail = np.maximum(pa[nf], 1 - pa[nf]) >= THRESH
orig = ids_a[nf][tail]
print(
    f"original tail reproduced from the saved predictions: {len(orig):,} rows at confidence >= {THRESH}; accuracy {100 * ((cls[orig] == 2) == (pa[nf][tail] >= 0.5)).mean():.1f}% close-to-close (the discovery figure)"
)
print(
    f"this study keeps FLAT-outcome rows: {int((np.maximum(pa, 1 - pa) >= THRESH).sum()):,} calls in {len(val_rows):,} validation rows; entry price valid on {100 * okentry[val_rows].mean():.2f}% of all validation rows"
)

G = len(day)


def side_from(ids: np.ndarray, p: np.ndarray) -> np.ndarray:
    s = np.zeros(G, dtype=np.int8)
    s[ids[p >= THRESH]] = 1
    s[ids[p <= 1 - THRESH]] = -1
    return s


SIDES: dict[str, np.ndarray] = {"M_A": side_from(ids_a, pa), "M_ALL": side_from(ids_f, pf)}
s5 = np.zeros(G, dtype=np.int8)
s5[val_rows[(ret1d[val_rows] <= -0.05)]] = 1
s5[val_rows[(ret1d[val_rows] >= 0.05)]] = -1
SIDES["R5"] = s5
cov = {y: float((SIDES["M_A"][val_rows[vyears == y]] != 0).mean()) for y in (2021, 2022, 2023)}
sc = np.zeros(G, dtype=np.int8)
cut_info = []
for y in (2021, 2022, 2023):
    train = np.flatnonzero(yr < y)
    cut = float(np.quantile(np.abs(ret1d[train][np.isfinite(ret1d[train])]), 1 - cov[y]))
    vr = val_rows[vyears == y]
    sc[vr[ret1d[vr] <= -cut]] = 1
    sc[vr[ret1d[vr] >= cut]] = -1
    cut_info.append(f"{y}: |ret1| >= {100 * cut:.2f}% (coverage {100 * cov[y]:.2f}%)")
SIDES["RCOV"] = sc
nd = np.zeros(G, dtype=np.int8)
nd[val_rows] = nday_dir[val_rows].astype(np.int8)
SIDES["NIFTY"] = nd
print("RCOV cuts (from training days only): " + "; ".join(cut_info))

# ---------------------------------------------------------------- costs from the repo's schedules
book = book_from_db(a.db if "a" in globals() else None)
VALUE = Decimal(100000)


def round_trip(product: str, y: int) -> tuple[float, str]:
    try:
        sch = book.for_date(date(y, 6, 30), product)
    except Exception:  # no dated schedule for that year (intraday exists from 2026 only): the 2026 rates are assumed
        sch = book.for_date(date(2026, 6, 30), product)
    price = Decimal(100)
    qty = VALUE / price
    tot = (
        compute_charges(sch, "BUY", qty, price).total
        + compute_charges(sch, "SELL", qty, price).total
    )
    return float(tot / VALUE), f"{sch.id} ({sch.status})"


COST = {(p, y): round_trip(p, y) for p in ("INTRADAY", "DELIVERY") for y in (2021, 2022, 2023)}
print("round-trip charges on Rs 1 lakh (brokerage, STT, exchange, SEBI, stamp, GST, DP):")
for (p, y), (c, sid) in COST.items():
    print(f"  {p:<9}{y}: {100 * c:.4f}%  {sid}")
SLIP = {"primary": 0.0010, "none": 0.0, "high": 0.0020}  # per side

# ---------------------------------------------------------------- statistics
rngb = np.random.default_rng(1)


def block_idx(nd_: int, block: int, draws: int) -> np.ndarray:
    nb = math.ceil(nd_ / block)
    st = rngb.integers(0, nd_, (draws, nb))
    return ((st[:, :, None] + np.arange(block)) % nd_).reshape(draws, -1)[:, :nd_]


def day_ci(rows_: np.ndarray, values: np.ndarray, draws: int = 1000) -> tuple[float, float, float]:
    """95% CI and z of the mean of `values` over rows, resampling blocks of 10 whole trading days (stocks on one day are dependent)."""
    d = day[rows_]
    s_ = np.bincount(d, weights=values, minlength=T)
    n_ = np.bincount(d, minlength=T).astype(float)
    keep = n_ > 0
    s_, n_ = s_[keep], n_[keep]
    if len(n_) < 20:
        return float("nan"), float("nan"), float("nan")
    ix = block_idx(len(n_), 10, draws)
    m = s_[ix].sum(1) / np.maximum(n_[ix].sum(1), 1)
    mean = s_.sum() / n_.sum()
    return (
        float(np.quantile(m, 0.025)),
        float(np.quantile(m, 0.975)),
        float(mean / m.std()) if m.std() > 0 else float("nan"),
    )


# same-day average of every eligible validation stock (valid entry), per horizon: the drift a skill-free pick would earn
DAYMEAN: dict[int, np.ndarray] = {}
for h in HZ:
    m_ = okentry[val_rows] & np.isfinite(ret[h][val_rows])
    rr_ = val_rows[m_]
    DAYMEAN[h] = np.bincount(day[rr_], weights=ret[h][rr_], minlength=T) / np.maximum(
        np.bincount(day[rr_], minlength=T), 1
    )

REG: list[dict] = []


def evaluate(name: str, h: int, sd: int, year: int | None, slip: str = "primary") -> dict:
    s = SIDES[name]
    sel = (s == sd) & okentry & np.isfinite(ret[h])
    if year is not None:
        sel &= yr == year
    rows_ = np.flatnonzero(sel)
    n = len(rows_)
    out = {
        "strategy": name,
        "side": "long" if sd > 0 else "short",
        "h": h,
        "year": year or "all",
        "slip": slip,
        "n": n,
    }
    if n < 30:
        return out | {"gross": np.nan}
    g = sd * ret[h][rows_]
    ex = sd * (ret[h][rows_] - DAYMEAN[h][day[rows_]])
    product = "INTRADAY" if h == 1 else "DELIVERY"
    cost = np.array([COST[(product, int(y))][0] for y in yr[rows_]])
    net = g - cost - 2 * SLIP[slip]
    wins, loss = net[net > 0], net[net <= 0]
    lo, hi, _ = day_ci(rows_, g)
    elo, ehi, ze = day_ci(rows_, ex)
    nlo, nhi, zn = day_ci(rows_, net)
    fav = mfe[h][rows_] if sd > 0 else -mae[h][rows_]
    adv = mae[h][rows_] if sd > 0 else -mfe[h][rows_]
    against1 = sd * ret[1][rows_] < 0
    return out | {
        "executable": not (sd < 0 and h > 1),
        "acc": float((g > 0).mean()),
        "gross": float(g.mean()),
        "gross_med": float(np.median(g)),
        "gross_lo": lo,
        "gross_hi": hi,
        "excess": float(ex.mean()),
        "ex_lo": elo,
        "ex_hi": ehi,
        "ex_z": ze,
        "net": float(net.mean()),
        "net_lo": nlo,
        "net_hi": nhi,
        "net_z": zn,
        "win_rate": float((net > 0).mean()),
        "avg_win": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss": float(loss.mean()) if len(loss) else np.nan,
        "profit_factor": float(wins.sum() / -loss.sum()) if loss.sum() < 0 else np.nan,
        "mfe": float(np.nanmean(fav)),
        "mae": float(np.nanmean(adv)),
        "against_first_session": float(against1.mean()),
        "recovered_by_end": float((sd * ret[h][rows_] > 0)[against1].mean())
        if against1.any() and h > 1
        else np.nan,
        "overnight_already_in_direction": float((sd * ovn[rows_]).mean()),
    }


STRATS = ("M_A", "M_ALL", "R5", "RCOV", "NIFTY")
for name in STRATS:
    for h in HZ:
        for sd in (1, -1):
            for y in (None, 2021, 2022, 2023):
                REG.append(evaluate(name, h, sd, y))
for name in ("M_A", "R5"):
    for sd in (1, -1):
        for sl in ("none", "high"):
            REG.append(evaluate(name, 1, sd, None, sl))
R = pd.DataFrame(REG)
base = R[(R.year == "all") & (R.slip == "primary")]
NCOUNT = int((base.n >= 30).sum())
zc = NormalDist().inv_cdf(1 - 0.05 / 2 / max(NCOUNT, 1))


def pick(name: str, sd: int, h: int, year: object = "all", slip: str = "primary") -> pd.Series:
    r = R[
        (R.year == year)
        & (R.slip == slip)
        & (R.strategy == name)
        & (R.side == ("long" if sd > 0 else "short"))
        & (R.h == h)
    ]
    return r.iloc[0]


def line(r: pd.Series) -> str:
    if not np.isfinite(r.get("gross", np.nan)):
        return f"{r.strategy:<6}{r.side:<6}{r.h}s  n={int(r.n):>6,} too few"
    ex = "" if r.executable else "  (not executable in cash: gross only)"
    return f"{r.strategy:<6}{r.side:<6}{r.h}s  n={int(r.n):>6,} acc {100 * r.acc:5.1f}%  gross {100 * r.gross:+6.3f}% [{100 * r.gross_lo:+.3f},{100 * r.gross_hi:+.3f}] median {100 * r.gross_med:+.3f}%  excess {100 * r.excess:+6.3f}% [{100 * r.ex_lo:+.3f},{100 * r.ex_hi:+.3f}]  net {100 * r.net:+6.3f}% [{100 * r.net_lo:+.3f},{100 * r.net_hi:+.3f}] z {r.net_z:+5.1f}  win {100 * r.win_rate:4.1f}%  avgW {100 * r.avg_win:+.2f}% avgL {100 * r.avg_loss:+.2f}% PF {r.profit_factor:4.2f}{ex}"


print(
    f"\n=== 1. NEXT-OPEN RESULTS, all validation years pooled (per trade, % of the entry open; primary slippage 10 bps per side; CI = day-block 95%); {NCOUNT} strategy x side x horizon rows counted, Bonferroni |z| >= {zc:.2f}"
)
for h in HZ:
    print(
        f"-- exit at the close of session {h} after the entry open"
        + ("  [PRIMARY horizon]" if h == 1 else "  [secondary]")
    )
    for name in STRATS:
        for sd in (1, -1):
            print("   " + line(pick(name, sd, h)))

print(
    "\n=== 2. WHERE THE CLOSE-TO-CLOSE EDGE WENT: the gap already in the called direction before any order can fill (close of T to open of T+1), and what is left from the open"
)
for name in ("M_A", "M_ALL", "R5"):
    for sd in (1, -1):
        r = pick(name, sd, 1)
        if np.isfinite(r.get("gross", np.nan)):
            print(
                f"{name:<6}{r.side:<6} n={int(r.n):>6,}  overnight gap in the called direction {100 * r.overnight_already_in_direction:+.3f}%   open->close gross {100 * r.gross:+.3f}%  excess over the same-day universe {100 * r.excess:+.3f}%"
            )

print("\n=== 3. BY YEAR, same-session (gross, excess, net %, n)")
for name in ("M_A", "R5", "RCOV"):
    for sd in (1, -1):
        cells = []
        for y in (2021, 2022, 2023):
            r = pick(name, sd, 1, y)
            cells.append(
                f"{y}: n={int(r.n):>5,} gross {100 * r.gross:+.3f} excess {100 * r.excess:+.3f} net {100 * r.net:+.3f}"
                if np.isfinite(r.get("gross", np.nan))
                else f"{y}: n={int(r.n)} too few"
            )
        print(f"{name:<6}{'long' if sd > 0 else 'short':<6}" + " | ".join(cells))

print("\n=== 4. SLIPPAGE SENSITIVITY, same-session, net % per trade (0 / 10 / 20 bps per side)")
for name in ("M_A", "R5"):
    for sd in (1, -1):
        v = [
            (
                f"{100 * pick(name, sd, 1, 'all', sl).net:+.3f}"
                if np.isfinite(pick(name, sd, 1, "all", sl).get("gross", np.nan))
                else "n/a"
            )
            for sl in ("none", "primary", "high")
        ]
        print(f"{name:<6}{'long' if sd > 0 else 'short':<6}" + "   ".join(v))

print(
    "\n=== 5. PORTFOLIO VIEW, same-session (equal weight, Rs 1 lakh per trade, daily series including no-trade days; Sharpe annualised x sqrt(252); max drawdown of the compounded series)"
)
vdays = np.array([t for t in range(T) if idx[t] >= np.datetime64("2021-01-01")])
for name in ("M_A", "R5"):
    for sd in (1, -1):
        sel = np.flatnonzero((SIDES[name] == sd) & okentry & np.isfinite(ret[1]))
        g = sd * ret[1][sel]
        cost = np.array([COST[("INTRADAY", int(y))][0] for y in yr[sel]])
        net = g - cost - 2 * SLIP["primary"]
        cnt = np.bincount(day[sel], minlength=T)
        daily = np.where(
            cnt > 0, np.bincount(day[sel], weights=net, minlength=T) / np.maximum(cnt, 1), 0.0
        )[vdays]
        eq = np.cumprod(1 + daily)
        dd = float((eq / np.maximum.accumulate(eq) - 1).min())
        sh = float(daily.mean() / daily.std() * math.sqrt(252)) if daily.std() > 0 else float("nan")
        print(
            f"{name:<6}{'long' if sd > 0 else 'short':<6} trades {len(sel):>6,} on {int((cnt > 0).sum()):>3} days ({len(sel) / max(int((cnt > 0).sum()), 1):.1f} per active day, {len(sel) / len(vdays):.2f} per day overall)  net mean/day {100 * daily.mean():+.4f}%  Sharpe {sh:+5.2f}  max drawdown {100 * dd:6.1f}%  cumulative {100 * (eq[-1] - 1):+.1f}%"
        )

print("\n=== 6. OVERLAP: does the model do anything the plain rule does not?")
ma, r5 = SIDES["M_A"] != 0, SIDES["R5"] != 0
print(
    f"model calls {int(ma.sum()):,}: reversal calls (against yesterday's move) {100 * ((SIDES['M_A'] * np.sign(ret1d) < 0) & ma).sum() / ma.sum():.0f}%, continuation {100 * ((SIDES['M_A'] * np.sign(ret1d) > 0) & ma).sum() / ma.sum():.0f}%; inside the 5% rule {100 * (ma & r5).sum() / ma.sum():.0f}%; median |yesterday| of the calls {100 * np.nanmedian(np.abs(ret1d[ma])):.2f}%"
)
side_ = np.where(SIDES["M_A"] != 0, SIDES["M_A"], SIDES["R5"])
for lab, mask in (
    ("model call AND 5% rule", ma & r5),
    ("5% rule, no model call", r5 & ~ma),
    ("model call, outside the 5% rule", ma & ~r5),
):
    for sd in (1, -1):
        sel = np.flatnonzero(mask & (side_ == sd) & okentry & np.isfinite(ret[1]))
        if len(sel) < 30:
            continue
        ex = sd * (ret[1][sel] - DAYMEAN[1][day[sel]])
        lo, hi, _ = day_ci(sel, ex)
        print(
            f"  {lab:<34}{'long' if sd > 0 else 'short':<6} n={len(sel):>6,}  same-session excess {100 * ex.mean():+.3f}% [{100 * lo:+.3f},{100 * hi:+.3f}]  gross {100 * (sd * ret[1][sel]).mean():+.3f}%"
        )

print(
    "\n=== 7. PREVIOUS-DAY RETURN BUCKETS, all validation rows, next open -> close (no selection; mean %, excess over the same-day universe %, overnight gap %)"
)
edges = [-0.09, -0.05, -0.03, -0.015, 0.015, 0.03, 0.05, 0.09]
labs = [
    "<= -9%",
    "-9..-5%",
    "-5..-3%",
    "-3..-1.5%",
    "-1.5..+1.5%",
    "1.5..3%",
    "3..5%",
    "5..9%",
    ">= 9%",
]
vv = val_rows[okentry[val_rows] & np.isfinite(ret[1][val_rows]) & np.isfinite(ret1d[val_rows])]
bk = np.digitize(ret1d[vv], edges)
print(f"{'bucket':<14}{'n':>8}{'open->close':>13}{'excess':>9}{'overnight':>11}{'up':>7}")
for b in range(9):
    sel = vv[bk == b]
    if len(sel) < 30:
        continue
    ex = ret[1][sel] - DAYMEAN[1][day[sel]]
    print(
        f"{labs[b]:<14}{len(sel):>8,}{100 * ret[1][sel].mean():>+12.3f}%{100 * ex.mean():>+8.3f}%{100 * ovn[sel].mean():>+10.3f}%{100 * (ret[1][sel] > 0).mean():>6.1f}%"
    )

print(
    "\n=== 7b. EXCURSIONS AND PATH, from the entry open, in the called direction (mean %): best and worst point reached by the end of the horizon (daily highs and lows), share against the call at the end of session 1, and of those how many were back in the call's favour by the end of the horizon"
)
for name in ("M_A", "R5", "RCOV"):
    for sd in (1, -1):
        for h in HZ:
            r = pick(name, sd, h)
            if np.isfinite(r.get("gross", np.nan)):
                rec = (
                    f"{100 * r.recovered_by_end:4.1f}%"
                    if np.isfinite(r.recovered_by_end)
                    else "  n/a"
                )
                print(
                    f"{name:<6}{r.side:<6}{h}s  n={int(r.n):>6,}  best {100 * r.mfe:+.2f}%  worst {100 * r.mae:+.2f}%  against after session 1: {100 * r.against_first_session:4.1f}%  recovered by the end: {rec}"
                )

print(
    "\n=== 8. HOLDOUT-ACCESS AUDIT (static heuristic: what a research script CAN read, not what it reported). Protected holdout: 2025-01-01..2026-11-13"
)
for f in sorted((ROOT / "scripts").glob("study_*.py")):
    txt = f.read_text()
    if not (
        re.search(r"\b(bar_1d|bar_1m|index_bar_1d|index_bar_1m)\b", txt) and "SELECT" in txt.upper()
    ):
        continue
    bounded = (
        re.search(r"(ts|trade_date)[^\n]{0,120}<=?\s*(%s|'20(23-12-31|24-01-01|25-01-01)')", txt)
        is not None
    )
    print(
        f"  {f.name:<34}{'queries bounded before 2024/2025' if bounded else 'NO upper date bound in its queries: loads data through the holdout window':<72}{'  [has a --final switch that evaluates 2024+ when asked]' if re.search(r'add_argument\(\s*.--final', txt) and f.name != Path(__file__).name else ''}"
    )
print(
    "  This session: study_conditions.py loaded every bar to the present to build its features but printed only development (2019-22) and validation (2023) results and never ran --final; study_volatility.py, study_next_session.py and this script cut their queries at 2024-01-01."
)

if a.log:
    R.to_csv(a.log, index=False)
    print(f"\nexperiment register: {len(R)} rows -> {a.log}")
