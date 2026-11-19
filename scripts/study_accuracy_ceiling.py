# ruff: noqa: E501
"""Study: with far more engineered features and both directions, how accurate can a call about the next few days be, honestly, on years the model never saw?

About 75 features known at each stock-day's close (multi-horizon returns, volatility, gaps, candle shape, distance from highs and lows, moving-average gaps and slopes, RSI, MACD,
volume and delivery against their norms, cross-sectional ranks, market breadth and dispersion, calendar, and the swing score's four parts as last known). Five things to call, each
with its own model, trained on 2019-2022 (trees chosen on 2023) and judged only on 2024 onward, with a gap so no training window overlaps what it is judged on:
  A  beats the median stock over the next 5 sessions               (balanced: 50% by construction)
  B  closes higher than today 5 sessions on                        (absolute up; the market drifts, so the base rate is above 50%)
  C  a long trade wins: +5% is reached before -3% within 10 sessions
  E  a short trade wins: -5% is reached before +3% within 10 sessions
  D  among the 5-session moves of 3% or more either way, which way it went (decisive moves only)
For each, the precision of the model's most confident calls at several coverages: the top x% as "yes" (up) and the bottom x% as "no" (down), with the number of cases and the
standard error, against the base rate. The question asked: does any combination reach 70-80% with enough cases to mean anything?
usage: study_accuracy_ceiling.py [--db URL] [--min-turnover-cr 5]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
        " FROM bar_1d WHERE source='nse' AND series='EQ' AND ts >= '2019-09-01' ORDER BY instrument_id, ts, dataset_version DESC"
    ).fetchall()
    splits = conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok'"
    ).fetchall()
    sc_rows = conn.execute(
        "SELECT day, instrument_id, score::float8, trend::float8, participation::float8, smart_money::float8, quality::float8 FROM stock_score_history"
    ).fetchall()
df = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v", "dq"])
del rows


def mat(frame: pd.DataFrame, col: str) -> pd.DataFrame:
    return frame.pivot(index="d", columns="iid", values=col).sort_index().astype("float32")


Op, H, L, C, V, DQ = (mat(df, k) for k in ("o", "h", "l", "c", "v", "dq"))
del df
T, S = C.shape
idx = C.index.values
dates_all = pd.to_datetime(C.index)

turnover = (C * V).rolling(20, min_periods=15).mean() / 1e7
bad = pd.DataFrame(False, index=C.index, columns=C.columns)
for iid, ex_date in splits:
    if iid in bad.columns:
        i = int(np.searchsorted(idx, np.datetime64(ex_date)))
        bad.iloc[max(0, i - 260) : min(T, i + 12), bad.columns.get_loc(iid)] = (
            True  # the longest look-back (250 sessions) and the longest look-ahead (10) must not cross a split
        )
fwd5 = C.shift(-5) / C - 1
liquid_df = (turnover >= a.min_turnover_cr) & ~bad & fwd5.notna() & C.shift(-10).notna()
liquid = liquid_df.to_numpy()
day_idx = np.nonzero(liquid)[0]
dates = idx[day_idx]
n_rows = int(liquid.sum())
print(
    f"{n_rows:,} liquid stock-days (turnover >= {a.min_turnover_cr} Cr, no split within 260 sessions before or 12 after, 10-session outcome known)\n"
)

cols: dict[str, np.ndarray] = {}


def add(name: str, frame: pd.DataFrame | np.ndarray) -> None:
    arr = frame.to_numpy() if isinstance(frame, pd.DataFrame) else frame
    cols[name] = arr[liquid].astype("float32")


def rank(
    frame: pd.DataFrame,
) -> pd.DataFrame:  # where the stock stands among the stocks of the same day, 0 to 1
    return frame.rank(axis=1, pct=True)


def broadcast(ser: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        np.broadcast_to(ser.to_numpy()[:, None], (T, S)), index=C.index, columns=C.columns
    )


ret1 = C.pct_change()
for k in (1, 2, 3, 5, 10, 20, 40, 60, 120, 250):
    add(f"r{k}", C / C.shift(k) - 1)
r5, r20, r60 = C / C.shift(5) - 1, C / C.shift(20) - 1, C / C.shift(60) - 1
R = H - L
body_hi, body_lo = np.maximum(Op, C), np.minimum(Op, C)
add("gap", Op / C.shift(1) - 1)
add("body", (C - Op) / Op)
add("range_pct", R / C)
add("loc", (C - L) / R.where(R > 0))
add("upper_wick", (H - body_hi) / R.where(R > 0))
add("lower_wick", (body_lo - L) / R.where(R > 0))
add("rng_ratio", R / R.shift(1).rolling(14, min_periods=14).mean())
for w in (5, 20, 60):
    add(f"vol{w}", ret1.rolling(w, min_periods=max(4, w // 2)).std() * 100)
add("atr14", R.rolling(14, min_periods=14).mean() / C * 100)
sma = {n: C.rolling(n, min_periods=n).mean() for n in (20, 50, 100, 200)}
for n, m in sma.items():
    add(f"g{n}", C / m - 1)
    add(f"slope{n}", m / m.shift(10) - 1)
ema9, ema21, ema12, ema26 = (C.ewm(span=s, adjust=False).mean() for s in (9, 21, 12, 26))
add("ema9_21", ema9 / ema21 - 1)
macd = ema12 - ema26
add("macdh", (macd - macd.ewm(span=9, adjust=False).mean()) / C * 100)
dl = C.diff()
rsi = 100 - 100 / (
    1
    + dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
)
add("rsi14", rsi)
lo14, hi14 = L.rolling(14, min_periods=14).min(), H.rolling(14, min_periods=14).max()
add("stoch14", (C - lo14) / (hi14 - lo14).where(hi14 > lo14))
for w in (20, 252):
    add(f"d{w}h", C / H.rolling(w, min_periods=int(w * 0.8)).max() - 1)
    add(f"d{w}l", C / L.rolling(w, min_periods=int(w * 0.8)).min() - 1)
add("up_days5", (ret1 > 0).astype("float32").rolling(5).sum())
add("up_days10", (ret1 > 0).astype("float32").rolling(10).sum())
bb_sd = C.rolling(20, min_periods=20).std()
bw = 4 * bb_sd / sma[20]
add("bw", bw)
add("bwr", bw / bw.rolling(120, min_periods=60).mean())
add("bb_pos", (C - sma[20]) / (2 * bb_sd).where(bb_sd > 0))
dpct = DQ / V.where(V > 0) * 100
add("dpct", dpct)
add("dpct5", DQ.rolling(5).sum() / V.rolling(5).sum() * 100)
add("dpct20", DQ.rolling(20, min_periods=15).sum() / V.rolling(20, min_periods=15).sum() * 100)
add("dratio", dpct / dpct.shift(1).rolling(20, min_periods=15).mean())
for w in (20, 60):
    vm, vs = (
        V.shift(1).rolling(w, min_periods=int(w * 0.75)).mean(),
        V.shift(1).rolling(w, min_periods=int(w * 0.75)).std(),
    )
    add(f"vz{w}", (V - vm) / vs.where(vs > 0))
    add(f"vr{w}", V / vm)
add("vr5", V.rolling(5).mean() / V.shift(5).rolling(20, min_periods=15).mean())
add("vol_trend", V.rolling(20, min_periods=15).mean() / V.rolling(60, min_periods=45).mean())
add("lturn", np.log(turnover + 1e-9))
add("lprice", np.log(C))
for name, fr in (
    ("r5", r5),
    ("r20", r20),
    ("r60", r60),
    ("vol20", ret1.rolling(20, min_periods=10).std()),
    ("dpct5", DQ.rolling(5).sum() / V.rolling(5).sum()),
    ("vr5", V.rolling(5).mean() / V.shift(5).rolling(20, min_periods=15).mean()),
    ("lturn", turnover),
):
    add(f"rk_{name}", rank(fr))
top252 = H.rolling(252, min_periods=200).max()
breadth50 = (C > sma[50]).where(sma[50].notna()).mean(axis=1)
breadth200 = (C > sma[200]).where(sma[200].notna()).mean(axis=1)
mk1, mk5, mk20, mk60 = (
    ret1.median(axis=1),
    r5.median(axis=1),
    r20.median(axis=1),
    r60.median(axis=1),
)
for name, ser in (
    ("breadth50", breadth50),
    ("breadth200", breadth200),
    ("mkt1", mk1),
    ("mkt5", mk5),
    ("mkt20", mk20),
    ("mkt60", mk60),
    ("disp", ret1.std(axis=1)),
    ("newhigh_share", (C >= top252).where(top252.notna()).mean(axis=1)),
    ("mktvol20", mk1.rolling(20, min_periods=10).std()),
):
    add(name, broadcast(ser))
add("rs5", r5.sub(mk5, axis=0))
add("rs20", r20.sub(mk20, axis=0))
add("rs60", r60.sub(mk60, axis=0))
add("dow", broadcast(pd.Series(dates_all.day_of_week.to_numpy(), index=C.index)))
add("month", broadcast(pd.Series(dates_all.month.to_numpy(), index=C.index)))

# ---- multiple time frames: weekly and monthly bars built from the daily ones, each known only once its period is over (a week counts from its Friday, a month from its last day) ----
dt = pd.DatetimeIndex(C.index)


def known(
    frame: pd.DataFrame,
) -> pd.DataFrame:  # a weekly/monthly table as last known on each day: reindexed forward from the period's closing label
    return frame.reindex(dt, method="ffill").set_axis(C.index, axis=0)


def ema_hist(c: pd.DataFrame) -> pd.DataFrame:
    m = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    return (m - m.ewm(span=9, adjust=False).mean()) / c * 100


def wilder_rsi(c: pd.DataFrame) -> pd.DataFrame:
    d = c.diff()
    return 100 - 100 / (
        1
        + d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        / (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    )


Cw, Hw, Vw = (
    C.set_axis(dt).resample("W-FRI").last(),
    H.set_axis(dt).resample("W-FRI").max(),
    V.set_axis(dt).resample("W-FRI").sum(),
)
wret = Cw.pct_change()
add("w_rsi", known(wilder_rsi(Cw)))
add("w_macdh", known(ema_hist(Cw)))
for n in (10, 30):
    add(f"w_g{n}", known(Cw / Cw.rolling(n, min_periods=n).mean() - 1))
for n in (1, 4, 13, 26):
    add(f"w_r{n}", known(Cw.pct_change(n)))
add("w_vol13", known(wret.rolling(13, min_periods=8).std() * 100))
w_sd = Cw.rolling(20, min_periods=20).std()
add("w_bbpos", known((Cw - Cw.rolling(20, min_periods=20).mean()) / (2 * w_sd).where(w_sd > 0)))
add("w_up4", known((wret > 0).astype("float32").rolling(4).sum()))
add("w_d52h", known(Cw / Hw.rolling(52, min_periods=40).max() - 1))
add("w_vr10", known(Vw / Vw.rolling(10, min_periods=8).mean().shift(1)))
Cm = C.set_axis(dt).resample("ME").last()
add("m_rsi", known(wilder_rsi(Cm)))
add("m_g10", known(Cm / Cm.rolling(10, min_periods=10).mean() - 1))
for n in (1, 3, 6, 12):
    add(f"m_r{n}", known(Cm.pct_change(n)))
add("m_vol12", known(Cm.pct_change().rolling(12, min_periods=8).std() * 100))
# do the frames agree? how many of the daily 50-day, weekly 10-week and monthly 10-month trends point up (0 to 3), and the same for momentum (RSI above 50 on daily, weekly, monthly)
trend_up = (
    (C > sma[50]).astype("float32")
    + known((Cw > Cw.rolling(10, min_periods=10).mean()).astype("float32"))
    + known((Cm > Cm.rolling(10, min_periods=10).mean()).astype("float32"))
)
add("align_trend", trend_up)
add(
    "align_rsi",
    (rsi > 50).astype("float32")
    + known((wilder_rsi(Cw) > 50).astype("float32"))
    + known((wilder_rsi(Cm) > 50).astype("float32")),
)
sc = pd.DataFrame(
    sc_rows, columns=["d", "iid", "score", "trend", "participation", "smart_money", "quality"]
)
sc["d"] = pd.to_datetime(sc["d"])
for k in ("score", "trend", "participation", "smart_money", "quality"):
    piv = sc.pivot(index="d", columns="iid", values=k)
    add(
        f"sw_{k}", piv.reindex(index=dates_all, columns=C.columns).ffill(limit=7).astype("float32")
    )  # the weekly swing score parts as last known, up to 7 days old
del sc, sc_rows

names = list(cols)
X = np.column_stack([cols[k] for k in names]).astype("float32")
cols.clear()
print(f"{len(names)} features\n")

# ---- the things to call ----
fwd5_f = fwd5.to_numpy()[liquid]
ex5 = fwd5.sub(fwd5.where(liquid_df).median(axis=1), axis=0).to_numpy()[liquid]


def first_touch(up: float, dn: float, days: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """(long wins, short wins): +up reached before -dn (long), and -up before +dn (short), within `days` sessions; a day touching both counts as a loss; neither in time is not a win."""
    long_win = np.zeros((T, S), dtype=bool)
    short_win = np.zeros_like(long_win)
    alive_l = np.ones((T, S), dtype=bool)
    alive_s = np.ones((T, S), dtype=bool)
    Hv, Lv, Cv = H.to_numpy(), L.to_numpy(), C.to_numpy()
    for k in range(1, days + 1):
        hk, lk = np.full((T, S), np.nan, dtype="float32"), np.full((T, S), np.nan, dtype="float32")
        hk[:-k], lk[:-k] = Hv[k:], Lv[k:]
        up_l, dn_l = hk >= Cv * (1 + up), lk <= Cv * (1 - dn)  # long: target up, stop down
        long_win |= alive_l & up_l & ~dn_l
        alive_l &= ~(up_l | dn_l)
        dn_s, up_s = lk <= Cv * (1 - up), hk >= Cv * (1 + dn)  # short: target down, stop up
        short_win |= alive_s & dn_s & ~up_s
        alive_s &= ~(dn_s | up_s)
    return long_win[liquid], short_win[liquid]


long_win, short_win = first_touch(0.05, 0.03)
everyone = np.ones(n_rows, dtype=bool)
targets = {
    "A  beats the median stock over 5 sessions": (ex5 > 0, everyone),
    "B  closes higher 5 sessions on": (fwd5_f > 0, everyone),
    "C  long trade wins: +5% before -3% in 10 sessions": (long_win, everyone),
    "E  short trade wins: -5% before +3% in 10 sessions": (short_win, everyone),
    "D  direction of 5-session moves of 3%+ either way": (fwd5_f > 0, np.abs(fwd5_f) >= 0.03),
}

gap = np.timedelta64(30, "D")
tr_end, va_end = np.datetime64("2023-01-01"), np.datetime64("2024-01-01")
tr = dates < (tr_end - gap)
va = (dates >= tr_end) & (dates < (va_end - gap))
te = dates >= va_end
print(
    f"train {tr.sum():,} rows (to 2022), choose trees on {va.sum():,} (2023), judge on {te.sum():,} (2024 onward)\n"
)


def precision_rows(score: np.ndarray, y: np.ndarray, day: np.ndarray) -> None:
    """Precision of the most confident calls, with how many different days they come from and the lift over the same day's base rate. A model that mostly says "the whole market goes up
    this week" has a high raw precision that sits on a few days and a within-day lift near zero: that is not skill at picking stocks."""
    base = y.mean()
    day_base = (
        pd.Series(y.astype(float)).groupby(day).transform("mean").to_numpy()
    )  # the share of 'yes' among all the judged cases of the same day
    print(
        f"   base rate of 'yes' on the judged rows: {100 * base:.1f}%  ({len(y):,} cases on {len(np.unique(day)):,} days)"
    )
    print(
        f"   {'coverage':<9}{'cases':>8}{'days':>6}  {'top say yes: right':>20}{'lift vs same day':>18}   {'bottom say no: right':>22}{'lift':>8}"
    )
    order = np.argsort(-score)
    for cov in (0.001, 0.005, 0.01, 0.02, 0.05, 0.10, 0.25):
        k = max(1, int(cov * len(score)))
        t, b = order[:k], order[-k:]
        print(
            f"   {100 * cov:>5.1f}%   {k:>8,}{len(np.unique(day[t])):>6}  {100 * y[t].mean():>14.1f}% ±{100 * np.sqrt(0.25 / k):3.1f}{100 * (y[t] - day_base[t]).mean():>+16.1f}pt   {100 * (1 - y[b]).mean():>16.1f}%{100 * (day_base[b] - y[b]).mean():>+8.1f}pt"
        )


for name, (y_all, keep) in targets.items():
    y = y_all.astype(np.int8)
    trk, vak, tek = tr & keep, va & keep, te & keep
    if y[trk].min() == y[trk].max():
        continue
    best_auc, model = 0.0, None
    for n_iter in (100, 200, 400):
        m = HistGradientBoostingClassifier(
            max_iter=n_iter,
            learning_rate=0.05,
            max_leaf_nodes=31,
            min_samples_leaf=500,
            l2_regularization=5.0,
            random_state=0,
        )
        m.fit(X[trk], y[trk])
        auc = roc_auc_score(y[vak], m.predict_proba(X[vak])[:, 1])
        if auc > best_auc:
            best_auc, model = auc, m
    p_te = model.predict_proba(X[tek])[:, 1]
    print(f"##### {name}")
    print(
        f"   {model.max_iter} trees; AUC on 2023 {best_auc:.4f}, on 2024 onward {roc_auc_score(y[tek], p_te):.4f} (0.5 = no skill)"
    )
    precision_rows(p_te, y[tek], day_idx[tek])
    rs = np.random.default_rng(0).choice(
        np.nonzero(vak)[0], size=min(40000, int(vak.sum())), replace=False
    )
    pi = permutation_importance(
        model, X[rs], y[rs], scoring="roc_auc", n_repeats=1, random_state=0, n_jobs=4
    )
    top = np.argsort(-pi.importances_mean)[:12]
    print("   leans on: " + ", ".join(f"{names[i]} {pi.importances_mean[i]:.4f}" for i in top))
    print()
