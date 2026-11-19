# ruff: noqa: E501
"""Controlled volatility study (2026-11-19), the follow-up to scripts/study_conditions.py section 5/6. DEFINITIONS FROZEN BEFORE THE FIRST RUN; the final holdout (2024+) is NOT read by this script.

Question: do breakout and price-extension conditions carry information about FUTURE LARGE MOVES that ATR%, recent volatility and the day's own range do not already carry, and is that information
stable and calibrated enough to show? Descriptive research only: no direction score, no trading signal.

Setup (all known at the close of day t; outcomes use days t+1..t+h only):
  features (10, frozen): brk20 (close over the prior 20-day high), candle15 (brk20 and the day's gain > 1.5 ATR), high52 (close over the prior 252-day high), tests3 (brk20 after >= 3 earlier tries at the level),
    base15 (brk20 after >= 15 bars in a range < 12%), ext3 (close > 3 ATR over its EMA20), rsi60, rsi40, relvol25 (volume >= 2.5x its 20-day mean), atrexp (5-day / 20-day true range > 1.3)
  outcomes at horizon h in 5/10/20 sessions, threshold k = 2 ATR (ATR14 at t) PRIMARY, 1.5 and 3 as sensitivity (h=10 only):
    up   = highest high in t+1..t+h reaches close(t) + k ATR        down = lowest low reaches close(t) - k ATR
    either = up or down        neither = not either (the complement; reported, not counted as a test)      bigA = (highest high - lowest low) / ATR(t) > 3, 4 (earlier definition) or 5
  control strata (80): ATR% quintile (edges from DEV only) x 5d/20d true-range ratio (<0.7, <1.0, <1.3, more) x same-day true range / prior ATR (<0.8, <1.2, <1.8, more). "Matched" = what days in the same
    stratum did anyway. Raw = against all liquid days. Both are reported; the matched one over-controls (a wide breakout day is part of what makes it informative) and the 80 strata are still coarse.
  tests counted: every (feature, outcome, h, k) in the primary, sensitivity and bigA families is one hypothesis; survivor bar is Bonferroni over that count (DEV), then t >= 2 same sign in VAL.
  periods: DEV 2019-2022, VAL 2023. Day-clustered 95% CI (overlapping windows: effective days = days / h).
  also: look-ahead audit of the controls, stability cuts (year, Nifty regime, market volatility, liquidity, sector), delisted-stock check, extended-stock decomposition, OLS check, calibration of a logistic model.
usage: study_volatility.py [--db URL] [--log tests.csv]"""

import argparse
import math
import os
import sys
from statistics import NormalDist

import numpy as np
import pandas as pd
import psycopg
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
ap.add_argument("--log", help="write every hypothesis tested to this CSV")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
HZS = (5, 10, 20)
VAL0 = np.datetime64("2023-01-01")
HOLD0 = np.datetime64("2024-01-01")  # never read: bars are cut here

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, high::float8, low::float8, close::float8, volume::float8"
        " FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= '2019-01-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date < '2024-01-01' ORDER BY instrument_id, ts, dataset_version DESC"
    ).fetchall()
    splits = conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ).fetchall()
    nifty = conn.execute(
        "SELECT trade_date, close::float8 FROM index_bar_1d WHERE symbol='NIFTY 50' AND trade_date >= '2018-06-01' AND trade_date < '2024-01-01' ORDER BY trade_date"
    ).fetchall()
    sect = conn.execute(
        "SELECT DISTINCT ON (instrument_id) instrument_id, sector FROM instrument_sector ORDER BY instrument_id, effective_from DESC"
    ).fetchall()
    dead = {
        int(r[0])
        for r in conn.execute("SELECT instrument_id FROM instrument WHERE delisted_on IS NOT NULL")
    }

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

# ---------------------------------------------------------------- features and controls (causal)
ema = lambda x, n: x.ewm(span=n, adjust=False, min_periods=n).mean()  # noqa: E731
pc = C.shift(1)
tr = np.maximum(H - L, np.maximum((H - pc).abs(), (L - pc).abs()))
atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
e20 = ema(C, 20)
dl = C.diff()
rsi = 100 - 100 / (
    1
    + dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
)
vavg = V.shift(1).rolling(20, min_periods=15).mean()
hi20, lo20 = (
    H.shift(1).rolling(20, min_periods=20).max(),
    L.shift(1).rolling(20, min_periods=20).min(),
)
hi52 = H.shift(1).rolling(252, min_periods=200).max()
brk20 = C > hi20
tight_np = (((hi20 - lo20) / C) < 0.12).to_numpy()
cv = np.zeros((T, S), dtype=np.float32)
for t in range(1, T):
    cv[t] = np.where(tight_np[t], cv[t - 1] + 1, 0)
cons = pd.DataFrame(cv, index=C.index, columns=C.columns)
nearhi = (H.shift(1) >= 0.99 * hi20).astype(float).rolling(40, min_periods=20).sum()
FEATS: dict[str, pd.DataFrame] = {
    "brk20": brk20,
    "candle15": brk20 & ((C - pc) > 1.5 * atr.shift(1)),
    "high52": C > hi52,
    "tests3": brk20 & (nearhi >= 3),
    "base15": brk20 & (cons.shift(1) >= 15),
    "ext3": (C - e20) > 3 * atr,
    "rsi60": rsi > 60,
    "rsi40": rsi < 40,
    "relvol25": V / vavg >= 2.5,
    "atrexp": tr.rolling(5).mean() / tr.rolling(20).mean() > 1.3,
}
FA = {k: v.fillna(False).to_numpy().astype(bool) for k, v in FEATS.items()}
atrp = (atr / C).to_numpy(dtype=np.float32)
r5 = (tr.rolling(5).mean() / tr.rolling(20).mean()).to_numpy(dtype=np.float32)
tdy = (tr / atr.shift(1)).to_numpy(dtype=np.float32)
turn = (C * V).rolling(20, min_periods=15).mean() / 1e7
lt = np.log10(turn.clip(lower=1e-3)).to_numpy(dtype=np.float32)
nsma50, nsma200 = NF.rolling(50, min_periods=50).mean(), NF.rolling(200, min_periods=200).mean()
mk_up = ((NF > nsma50) & (nsma50 > nsma50.shift(10)) & (nsma50 > nsma200)).fillna(False).to_numpy()
mk_dn = ((NF < nsma50) & (nsma50 < nsma50.shift(10))).fillna(False).to_numpy()
nrv = NF.pct_change().rolling(20, min_periods=20).std()
mk_hv = (nrv > nrv.rolling(250, min_periods=120).median()).fillna(False).to_numpy()
sec = pd.Series(dict(sect)).reindex(C.columns).to_numpy()
DEAD = np.array([int(i) in dead for i in C.columns])
bad = pd.DataFrame(False, index=C.index, columns=C.columns)
for iid, exd in splits:
    if iid in bad.columns:
        i = int(np.searchsorted(idx, np.datetime64(exd)))
        bad.iloc[max(0, i - 25) : min(T, i + 22), bad.columns.get_loc(iid)] = True
base_ok = (
    ((turn >= a.min_turnover_cr) & ~bad & atr.notna()).to_numpy()
    & np.isfinite(r5)
    & np.isfinite(tdy)
)

per = np.where(idx >= VAL0, 1, 0)[:, None]  # 0 DEV, 1 VAL (the holdout is not loaded)
day = np.broadcast_to(np.arange(T)[:, None], (T, S))
year = (idx.astype("datetime64[Y]").astype(int) + 1970)[:, None]
edges = np.nanquantile(atrp[base_ok & (per == 0)], [0.2, 0.4, 0.6, 0.8])
STRAT = (
    np.digitize(np.nan_to_num(atrp), edges) * 16
    + np.digitize(np.nan_to_num(r5), [0.7, 1.0, 1.3]) * 4
    + np.digitize(np.nan_to_num(tdy), [0.8, 1.2, 1.8])
)
NS = 80

OUT: dict[int, dict[str, np.ndarray]] = {}
for h in HZS:
    hmax, lmin = (
        H.rolling(h).max().shift(-h),
        L.rolling(h).min().shift(-h),
    )  # the max/min of days t+1..t+h
    OUT[h] = dict(
        up=(hmax / C - 1).to_numpy(dtype=np.float32),
        dn=(lmin / C - 1).to_numpy(dtype=np.float32),
        rng=((hmax - lmin) / atr).to_numpy(dtype=np.float32),
        fw=(C.shift(-h) / C - 1).to_numpy(dtype=np.float32),
    )
    OUT[h]["ok"] = base_ok & np.isfinite(OUT[h]["up"]) & np.isfinite(OUT[h]["dn"])
print(
    f"{S} stocks ({int(DEAD.sum())} delisted), {T} days {str(idx[0])[:10]}..{str(idx[-1])[:10]} (holdout not loaded); {NS} control strata"
)


def outcome(kind: str, h: int, k: float) -> np.ndarray:
    o = OUT[h]
    if kind == "up":
        return o["up"] >= k * atrp
    if kind == "down":
        return o["dn"] <= -k * atrp
    if kind == "either":
        return (o["up"] >= k * atrp) | (o["dn"] <= -k * atrp)
    if kind == "neither":
        return ~((o["up"] >= k * atrp) | (o["dn"] <= -k * atrp))
    return o["rng"] > k  # bigA


RATE_CACHE: dict[tuple, np.ndarray] = {}


def rates(y: np.ndarray, ok: np.ndarray, pm: np.ndarray, key: tuple) -> np.ndarray:
    if key not in RATE_CACHE:
        m = ok & pm
        RATE_CACHE[key] = np.bincount(STRAT[m], weights=y[m], minlength=NS) / np.maximum(
            np.bincount(STRAT[m], minlength=NS), 1
        )
    return RATE_CACHE[key]


TESTS: list[dict] = []


def cell(
    mask: np.ndarray,
    kind: str,
    h: int,
    k: float,
    p: int,
    pm: np.ndarray | None = None,
    tag: str = "",
) -> dict:
    """One feature, one outcome, one period: absolute and matched probabilities, the differences and a day-clustered 95% CI of the matched difference."""
    y = outcome(kind, h, k)
    ok = OUT[h]["ok"]
    pmask = (per == p) if pm is None else pm
    rt = rates(y, ok, pmask, (kind, h, k, p if pm is None else tag))
    sel = mask & ok & pmask
    n = int(sel.sum())
    r = dict(
        n=n,
        base=np.nan,
        p=np.nan,
        exp=np.nan,
        d_raw=np.nan,
        d_ctl=np.nan,
        lo=np.nan,
        hi=np.nan,
        lift_raw=np.nan,
        lift_ctl=np.nan,
        z=np.nan,
    )
    if n < 100:
        return r
    base = y[ok & pmask].mean()
    pr = y[sel].mean()
    res = y[sel] - rt[STRAT[sel]]
    d = day[sel]
    cnt = np.bincount(d, minlength=T)
    pw = np.bincount(d, weights=res, minlength=T)[cnt > 0] / cnt[cnt > 0]
    se = pw.std(ddof=1) / math.sqrt(max(len(pw) / h, 1)) if len(pw) > 5 else np.nan
    ex = pr - res.mean()
    r.update(
        base=100 * base,
        p=100 * pr,
        exp=100 * ex,
        d_raw=100 * (pr - base),
        d_ctl=100 * res.mean(),
        lo=100 * (res.mean() - 1.96 * se),
        hi=100 * (res.mean() + 1.96 * se),
        lift_raw=pr / base if base else np.nan,
        lift_ctl=pr / ex if ex else np.nan,
        z=res.mean() / se if se else np.nan,
    )
    return r


def fmt(r: dict) -> str:
    return f"n={r['n']:>7,} P{r['p']:5.1f}% base{r['base']:5.1f}% matched{r['exp']:5.1f}% raw{r['d_raw']:+5.1f}pp ctl{r['d_ctl']:+5.1f}pp [{r['lo']:+5.1f},{r['hi']:+5.1f}] x{r['lift_raw']:4.2f}/{r['lift_ctl']:4.2f}"


def run(fam: str, kind: str, h: int, k: float, show: bool = True, count: bool = True) -> None:
    for f in FA:
        rr = [cell(FA[f], kind, h, k, p) for p in (0, 1)]
        if count:
            for p, r in zip((0, 1), rr, strict=True):
                TESTS.append(
                    dict(family=fam, feature=f, outcome=kind, h=h, k=k, per=("DEV", "VAL")[p], **r)
                )
        if show:
            print(f"{f:<9}{kind:<8}{h:>2}d k{k:<3} DEV {fmt(rr[0])} | VAL {fmt(rr[1])}")


print(
    "\n=== A. PRIMARY: up / down / either at 2 ATR, 5, 10, 20 sessions (absolute probabilities; raw lift / matched lift; 95% CI of the matched difference)"
)
for h in HZS:
    for kind in ("up", "down", "either"):
        run("primary", kind, h, 2.0)
        print()
print("neither (complement of either, h=10, not counted as a test):")
run("neither", "neither", 10, 2.0, count=False)

print(
    "\n=== B. SENSITIVITY: thresholds 1.5 and 3 ATR at 10 sessions, and the earlier 'big move' (range > 3, 4, 5 ATR)"
)
for k in (1.5, 3.0):
    for kind in ("up", "down", "either"):
        run("sens", kind, 10, k)
for k in (3.0, 4.0, 5.0):
    run("bigA", "bigA", 10, k)

N = len(
    {
        (t["family"], t["feature"], t["outcome"], t["h"], t["k"])
        for t in TESTS
        if t["family"] in ("primary", "sens", "bigA")
    }
)
zc = NormalDist().inv_cdf(1 - 0.05 / 2 / N)
print(
    f"\n=== C. SURVIVORS: {N} hypotheses counted, Bonferroni z >= {zc:.2f} in DEV (matched difference positive), z >= 2 and the same sign in VAL, n >= 300 in VAL"
)
dev = {
    (t["family"], t["feature"], t["outcome"], t["h"], t["k"]): t for t in TESTS if t["per"] == "DEV"
}
val = {
    (t["family"], t["feature"], t["outcome"], t["h"], t["k"]): t for t in TESTS if t["per"] == "VAL"
}
SURV = []
for key, d_ in dev.items():
    v_ = val[key]
    if (
        d_["n"] >= 300
        and v_["n"] >= 300
        and np.isfinite(d_["z"])
        and abs(d_["z"]) >= zc
        and d_["z"] * v_["z"] > 0
        and abs(v_["z"]) >= 2
    ):
        SURV.append(key)
        print(
            f"{key[1]:<9}{key[2]:<8}{key[3]:>2}d k{key[4]:<3} DEV ctl{d_['d_ctl']:+5.1f}pp z{d_['z']:+5.1f} | VAL ctl{v_['d_ctl']:+5.1f}pp z{v_['z']:+5.1f}  (P {d_['p']:.1f}%/{v_['p']:.1f}% vs matched {d_['exp']:.1f}%/{v_['exp']:.1f}%)"
        )
if not SURV:
    print("(none)")

KEYF = ["brk20", "candle15", "high52", "ext3", "rsi60"]
print(
    "\n=== D. STABILITY (DEV+VAL together, outcome 'either' at 2 ATR, 10 sessions): matched difference in pp [n]; a finding should keep its sign in most cells"
)
both = per <= 1
groups: dict[str, np.ndarray] = {f"year {y}": year == y for y in range(2019, 2024)}
groups |= {
    "Nifty up": mk_up[:, None],
    "Nifty down": mk_dn[:, None],
    "Nifty sideways": (~mk_up & ~mk_dn)[:, None],
    "high-vol market": mk_hv[:, None],
    "low-vol market": ~mk_hv[:, None],
}
qs = np.nanquantile(lt[base_ok & both], [1 / 3, 2 / 3])
groups |= {
    "liquidity low": lt < qs[0],
    "liquidity mid": (lt >= qs[0]) & (lt < qs[1]),
    "liquidity high": lt >= qs[1],
}
big_secs = pd.Series(sec).value_counts().head(6).index
groups |= {f"sector {s}": np.broadcast_to((sec == s)[None, :], (T, S)) for s in big_secs}
print(f"{'group':<34}" + "".join(f"{f:>16}" for f in KEYF))
for gname, gm in groups.items():
    cells = []
    for f in KEYF:
        r = cell(FA[f] & gm, "either", 10, 2.0, 0, pm=both, tag="all")
        cells.append(f"{r['d_ctl']:+5.1f} [{r['n']:>5,}]" if r["n"] >= 100 else f"{'-':>12}")
    print(f"{gname:<34}" + "".join(f"{c:>16}" for c in cells))

print(
    f"\n=== E. SURVIVORSHIP: delisted stocks are {100 * DEAD.mean():.1f}% of columns and {100 * (base_ok & DEAD[None, :]).sum() / base_ok.sum():.2f}% of liquid stock-days; matched difference (either, 2 ATR, 10 sessions) with all stocks vs without the delisted ones"
)
for f in KEYF:
    r_all = cell(FA[f], "either", 10, 2.0, 0, pm=both, tag="all")
    r_live = cell(FA[f] & ~DEAD[None, :], "either", 10, 2.0, 0, pm=both, tag="all")
    print(
        f"{f:<9} all {r_all['d_ctl']:+5.1f}pp (n={r_all['n']:,})   live only {r_live['d_ctl']:+5.1f}pp (n={r_live['n']:,})"
    )

print(
    "\n=== F. EXTENDED STOCKS (ext3, > 3 ATR over EMA20): what it overlaps with, and up / down / either at 2 ATR, 10 sessions (matched difference, pp, DEV | VAL)"
)
e3 = FA["ext3"]
subs = {
    "ext3 (all)": e3,
    "ext3 & brk20": e3 & FA["brk20"],
    "ext3 & not brk20": e3 & ~FA["brk20"],
    "ext3 & up day": e3 & (C > pc).to_numpy(),
    "ext3 & down day": e3 & (C <= pc).to_numpy(),
    "ext3 & within 5% of 52w high": e3 & (C >= 0.95 * hi52).to_numpy(),
    "ext3 & rsi60": e3 & FA["rsi60"],
    "ext3 & relvol25": e3 & FA["relvol25"],
    "ext3 & Nifty up": e3 & mk_up[:, None],
    "ext3 & Nifty not up": e3 & ~mk_up[:, None],
}
for nm, m in subs.items():
    cs = []
    for kind in ("up", "down", "either"):
        r0, r1 = cell(m, kind, 10, 2.0, 0), cell(m, kind, 10, 2.0, 1)
        cs.append(f"{kind} {r0['d_ctl']:+5.1f}|{r1['d_ctl']:+5.1f}")
    r0 = cell(m, "either", 10, 2.0, 0)
    print(f"{nm:<30} n DEV={r0['n']:>6,}  " + "   ".join(cs))

print(
    "\n=== G. REGRESSION CHECK: linear probability of 'either' (2 ATR, 10 sessions) on continuous controls + all 10 features; coefficient in pp (per period)"
)
okh = OUT[10]["ok"]
y10 = outcome("either", 10, 2.0)
names = list(FA)
for p, pn in ((0, "DEV"), (1, "VAL")):
    m = okh & (per == p)
    X = np.column_stack(
        [np.ones(m.sum(), dtype=np.float32), atrp[m], atrp[m] ** 2, r5[m], tdy[m], lt[m]]
        + [FA[f][m].astype(np.float32) for f in names]
    )
    beta, *_ = np.linalg.lstsq(X, y10[m].astype(np.float32), rcond=None)
    print(
        f"{pn}: " + "  ".join(f"{f} {100 * b:+.1f}" for f, b in zip(names, beta[6:], strict=True))
    )
    del X

print(
    "\n=== H. CALIBRATION: logistic model of 'either' (2 ATR, 10 sessions), fitted on DEV, scored on VAL; controls only vs controls + 10 features"
)
rng_ = np.random.default_rng(0)
mtr, mte = okh & (per == 0), okh & (per == 1)
itr = np.flatnonzero(mtr.ravel())
ite = np.flatnonzero(mte.ravel())
itr, ite = (
    rng_.choice(itr, min(len(itr), 600_000), replace=False),
    rng_.choice(ite, min(len(ite), 400_000), replace=False),
)


def pick(ii: np.ndarray, with_feats: bool) -> np.ndarray:
    cols = [
        atrp.ravel()[ii],
        atrp.ravel()[ii] ** 2,
        r5.ravel()[ii],
        tdy.ravel()[ii],
        lt.ravel()[ii],
    ] + ([FA[f].ravel()[ii].astype(np.float32) for f in names] if with_feats else [])
    return np.column_stack(cols).astype(np.float32)


ytr, yte = y10.ravel()[itr], y10.ravel()[ite]
pt = np.array([])
for wf in (False, True):
    xtr, xte = pick(itr, wf), pick(ite, wf)
    mu, sd = xtr.mean(0), xtr.std(0) + 1e-9
    lr = LogisticRegression(max_iter=300).fit((xtr - mu) / sd, ytr)
    pt = lr.predict_proba((xte - mu) / sd)[:, 1]
    print(
        f"{'controls + features' if wf else 'controls only':<20} VAL Brier {brier_score_loss(yte, pt):.5f}  logloss {log_loss(yte, pt):.5f}  AUC {roc_auc_score(yte, pt):.4f}   (base rate DEV {100 * ytr.mean():.1f}% / VAL {100 * yte.mean():.1f}%)"
    )
q = np.quantile(pt, np.linspace(0, 1, 11))
bins = np.clip(np.digitize(pt, q[1:-1]), 0, 9)
print("calibration of controls + features on VAL (predicted vs observed, by decile):")
gap = 0.0
for b in range(10):
    s = bins == b
    gap = max(gap, abs(pt[s].mean() - yte[s].mean()))
    print(
        f"  decile {b + 1:>2}: predicted {100 * pt[s].mean():5.1f}%  observed {100 * yte[s].mean():5.1f}%  n={int(s.sum()):,}"
    )
print(
    f"largest gap {100 * gap:.1f} pp (VAL base rate {100 * yte.mean():.1f}%: DEV and VAL rates differ, so a gap of that order is a level shift, not noise)"
)

if a.log:
    pd.DataFrame(TESTS).to_csv(a.log, index=False)
    print(f"\nwrote {len(TESTS)} test rows to {a.log}")
