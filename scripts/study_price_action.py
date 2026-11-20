# ruff: noqa: E501
"""Study: can PURE price action (open/high/low/close only; no volume, delivery, fundamentals, news, index) say which stocks to buy and which to sell?

Row = (stock, day t). Features use bars up to t only. Entry = open of t+1, exit = close of t+H (H sessions).
Target = the forward return minus the same-day median of all stocks (market-neutral, so a rising market cannot fake skill).
Model: one pooled gradient-boosting classifier P(beats the day's median), trained 2019-2022, judged on 2024+ (2023 is a gap). Prices: Kite adjusted daily bars; costs: the repo's DB cost schedules + slippage (study_common). Control: same model, shuffled labels.
Judged by: AUC; top and bottom decile of the model's score, mean excess and mean raw return per trade, non-overlapping days only (every H-th day), t-stat across those days, by year.
Also a few classic rules (breakout, oversold, trend...) judged the same way, as a plain-rule baseline.
Costs: 0.5% round trip is subtracted from the long side; short side shown gross and net (cash-market shorting is intraday only in India: treat the short side as an AVOID signal).
usage: study_price_action.py [--db URL] [--n 300] [--horizon 5] [--seed 0]"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from study_common import BARS, Costs, describe, flat_cost, vec_round_trip  # noqa: E402,I001

DEV_END = json.loads(
    (Path(__file__).resolve().parent.parent / "config/research_holdout.json").read_text()
)["development_end"]  # a study never reads the protected holdout window

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--n", type=int, default=300)
ap.add_argument("--horizon", type=int, default=5)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument(
    "--geo",
    action="store_true",
    help="add trendline / fibonacci / pivot support-resistance features",
)
ap.add_argument("--vp", action="store_true", help="add volume-profile features (uses volume)")
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
H, COST = a.horizon, flat_cost()
TRAIN_END, TEST_START = pd.Timestamp("2022-12-31"), pd.Timestamp("2024-01-01")

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= '2019-09-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= %s ORDER BY instrument_id, ts, dataset_version DESC",
        (DEV_END,),
    ).fetchall()
bars = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
del rows
bars["d"] = pd.to_datetime(bars["d"])
turn = (bars["c"] * bars["v"] / 1e7).groupby(bars["iid"]).median()
n_bars = bars.groupby("iid").size()
ok = [
    int(i)
    for i in n_bars.index[(n_bars >= 1300) & (turn.reindex(n_bars.index) >= a.min_turnover_cr)]
]
rng = np.random.default_rng(a.seed)
ids = sorted(rng.choice(ok, size=a.n, replace=False).tolist()) if 0 < a.n < len(ok) else ok
print(f"{len(ok)} liquid stocks with 1300+ bars; using {len(ids)}; horizon {H} sessions")

FEATS: list[str] = []


def stock_frame(iid: int, d: pd.DataFrame) -> pd.DataFrame:
    d = d.set_index("d").sort_index()
    o, h, lo, c = (d[k] for k in ("o", "h", "l", "c"))
    pc = c.shift(1)
    atr = (
        pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1)
        .max(axis=1)
        .rolling(14, min_periods=14)
        .mean()
    )
    lr = np.log(c / pc)
    vol20 = lr.rolling(20, min_periods=15).std()
    rng_ = (h - lo).replace(0, np.nan)
    f = pd.DataFrame(index=d.index)
    for k in (1, 2, 3, 5, 10, 20, 60):
        f[f"ret{k}"] = np.log(c / c.shift(k)) / (vol20 * np.sqrt(k))  # move in own-volatility units
    f["range_atr"] = (h - lo) / atr
    f["body"] = (c - o) / rng_
    f["up_wick"] = (h - np.maximum(o, c)) / rng_
    f["lo_wick"] = (np.minimum(o, c) - lo) / rng_
    f["close_pos"] = (c - lo) / rng_
    f["gap_atr"] = (o - pc) / atr
    for k in (20, 50, 200):
        f[f"dist_sma{k}"] = (c - c.rolling(k, min_periods=k).mean()) / atr
    for k in (20, 252):
        hi, low = (
            h.rolling(k, min_periods=int(k * 0.8)).max(),
            lo.rolling(k, min_periods=int(k * 0.8)).min(),
        )
        f[f"pos{k}"] = (c - low) / (hi - low).replace(0, np.nan)
    f["days_since_hi20"] = h.rolling(20).apply(lambda x: 19 - int(np.argmax(x)), raw=True)
    up = (lr > 0).astype(int)
    grp = (up != up.shift()).cumsum()
    f["streak"] = up.groupby(grp).cumcount().add(1) * np.where(up == 1, 1, -1)
    f["inside"] = ((h < h.shift()) & (lo > lo.shift())).astype(float)
    f["nr7"] = ((h - lo) == (h - lo).rolling(7).min()).astype(float)
    f["atr_pct"] = atr / c
    f["vol_ratio"] = vol20 / lr.rolling(100, min_periods=60).std()
    # geometry (g_*): trendlines, fibonacci, pivot support/resistance. All use bars up to t only.
    for n in (30, 60):
        w = np.arange(n) - (n - 1) / 2
        for nm, s in (("lo", lo), ("hi", h)):
            slope = (
                pd.Series(np.convolve(s.to_numpy(), w[::-1], mode="full")[: len(s)], index=s.index)
                / (w**2).sum()
            )
            line_end = s.rolling(n).mean() + slope * (n - 1) / 2  # regression line's value at t
            f[f"g_{nm}_slope{n}"] = slope / atr
            f[f"g_{nm}_dist{n}"] = (c - line_end) / atr
    hi60, lo60 = h.rolling(60).max(), lo.rolling(60).min()
    up_swing = h.rolling(60).apply(lambda x: np.argmax(x), raw=True) > lo.rolling(60).apply(
        lambda x: np.argmin(x), raw=True
    )
    retr = np.where(
        up_swing,
        (hi60 - c) / (hi60 - lo60).replace(0, np.nan),
        (c - lo60) / (hi60 - lo60).replace(0, np.nan),
    )
    f["g_fib_retr"] = retr  # 0 = at the swing extreme, 1 = fully retraced
    f["g_fib_up_swing"] = up_swing.astype(float)
    f["g_fib_near"] = (
        pd.DataFrame({k: (np.abs(retr - k) < 0.03) for k in (0.382, 0.5, 0.618)}, index=d.index)
        .any(axis=1)
        .astype(float)
    )
    pl = (
        lo.where(lo == lo.rolling(11, center=True).min()).shift(5).ffill()
    )  # pivot low, known 5 bars later
    ph = h.where(h == h.rolling(11, center=True).max()).shift(5).ffill()
    f["g_sup_dist"] = (c - pl) / atr
    f["g_res_dist"] = (ph - c) / atr
    if a.vp:  # volume profile (v_*) over the last 60 sessions; each bar's volume spread evenly over its high-low range
        n, nb = 60, 30
        if len(d) > n:
            sw = np.lib.stride_tricks.sliding_window_view
            Hh, Ll, Vv = (sw(s.to_numpy(), n, axis=0) for s in (h, lo, d["v"]))
            pmin, pmax = Ll.min(1), Hh.max(1)
            step = np.maximum((pmax - pmin) / nb, 1e-9)
            lo_e = pmin[:, None] + step[:, None] * np.arange(nb)
            hi_e = lo_e + step[:, None]
            ov = np.clip(
                np.minimum(Hh[:, :, None], hi_e[:, None, :])
                - np.maximum(Ll[:, :, None], lo_e[:, None, :]),
                0,
                None,
            )
            prof = (ov / np.maximum(Hh - Ll, 1e-9)[:, :, None] * Vv[:, :, None]).sum(
                1
            )  # (windows, bins)
            tot = prof.sum(1)
            order = np.argsort(-prof, axis=1)
            sp = np.take_along_axis(prof, order, 1)
            inc = np.zeros_like(prof, dtype=bool)
            np.put_along_axis(
                inc, order, (np.cumsum(sp, 1) - sp) < 0.7 * tot[:, None], 1
            )  # bins making up 70% of volume
            vah = np.where(inc, hi_e, -np.inf).max(1)
            val = np.where(inc, lo_e, np.inf).min(1)
            poc = np.take_along_axis(lo_e, prof.argmax(1)[:, None], 1)[:, 0] + step / 2
            cc, aa = c.to_numpy()[n - 1 :], atr.to_numpy()[n - 1 :]
            bi = np.clip(((cc - pmin) / step).astype(int), 0, nb - 1)
            vp = pd.DataFrame(
                {
                    "v_poc_dist": (cc - poc) / aa,
                    "v_vah_dist": (cc - vah) / aa,
                    "v_val_dist": (cc - val) / aa,
                    "v_in_va": ((cc >= val) & (cc <= vah)).astype(float),
                    "v_va_width": (vah - val) / aa,
                    "v_dens_close": np.take_along_axis(prof, bi[:, None], 1)[:, 0] / prof.max(1),
                },
                index=d.index[n - 1 :],
            )
            f = f.join(vp)
        f["v_rel_vol"] = d["v"] / d["v"].rolling(20, min_periods=15).mean()
    # rules (plain price-action recipes) as 0/1 flags
    f["r_breakout20"] = (c > h.shift().rolling(20).max()).astype(float)
    f["r_breakdown20"] = (c < lo.shift().rolling(20).min()).astype(float)
    f["r_oversold_up"] = ((f["ret3"] < -1.5) & (c > c.rolling(200, min_periods=200).mean())).astype(
        float
    )
    f["r_overbought"] = (f["ret3"] > 1.5).astype(float)
    f["r_trend"] = (
        (c > c.rolling(50).mean()) & (c.rolling(50).mean() > c.rolling(200, min_periods=200).mean())
    ).astype(float)
    f["r_bull_engulf"] = (
        (c > o) & (c.shift() < o.shift()) & (c >= o.shift()) & (o <= c.shift())
    ).astype(float)
    f["r_bear_engulf"] = (
        (c < o) & (c.shift() > o.shift()) & (c <= o.shift()) & (o >= c.shift())
    ).astype(float)
    # forward return: next open -> close at t+H
    f["fwd"] = c.shift(-H) / o.shift(-1) - 1
    f["o1"] = o.shift(-1)  # next open: where a signal acts
    f["turn1"] = (c * d["v"]).shift(-1)  # next session traded value (slippage input)
    f["iid"] = iid
    return f


parts = []
g = bars[bars["iid"].isin(ids)].groupby("iid")
for iid, d in g:
    fr = stock_frame(int(iid), d)
    if len(fr):
        parts.append(fr)
del bars
df = pd.concat(parts).reset_index().rename(columns={"d": "date"})
df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["fwd", "ret60", "dist_sma200", "pos252"])
df["excess"] = df["fwd"] - df.groupby("date")["fwd"].transform("median")
df = df[df.groupby("date")["iid"].transform("size") >= 30]
FEATS = [
    c
    for c in df.columns
    if c not in ("date", "iid", "fwd", "excess", "o1", "turn1")
    and (a.geo or not c.startswith("g_"))
    and (a.vp or not c.startswith("v_"))
]
print("geometry features (trendline, fibonacci, pivot S/R):", "ON" if a.geo else "off")
print(f"{len(df):,} rows, {df['date'].nunique()} days, {len(FEATS)} features")

train = df[df["date"] <= TRAIN_END]
test = df[df["date"] >= TEST_START].copy()
y_tr = (train["excess"] > 0).astype(int).to_numpy()
y_te = (test["excess"] > 0).astype(int).to_numpy()


def fit(y: np.ndarray) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_depth=4,
        learning_rate=0.05,
        max_iter=200,
        min_samples_leaf=500,
        l2_regularization=5.0,
        random_state=0,
    ).fit(train[FEATS], y)


m_main = fit(y_tr)
test["p"] = m_main.predict_proba(test[FEATS])[:, 1]
test["p_ctrl"] = fit(rng.permutation(y_tr)).predict_proba(test[FEATS])[:, 1]
print(
    f"\nAUC(beats day median)  model {roc_auc_score(y_te, test['p']):.4f}   shuffled-label control {roc_auc_score(y_te, test['p_ctrl']):.4f}   (0.5 = luck)"
)


def ttest(x: pd.Series) -> tuple[float, float]:
    x = x.dropna()
    if len(x) < 3 or x.std() == 0:
        return float(x.mean()), float("nan")
    return float(x.mean()), float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


# non-overlapping entry days: every H-th trading day
days = sorted(test["date"].unique())
pick = set(days[::H])
nt = test[test["date"].isin(pick)].copy()
nt["year"] = nt["date"].dt.year

print(
    f"\nTest {TEST_START.date()}+, non-overlapping entries every {H} days ({len(pick)} entry days). Mean per trade, per entry-day basket:"
)
print(f"{'signal':<32}{'n/day':>6}{'excess%':>9}{'t':>6}{'raw%':>8}{'net%':>8}  by year (excess%)")


def report(name: str, sel: pd.Series, short: bool = False) -> None:
    sign = -1 if short else 1
    ex = sign * nt[sel].groupby("date")["excess"].mean()
    raw = sign * nt[sel].groupby("date")["fwd"].mean()
    m, t = ttest(ex)
    yrs = " ".join(
        f"{y}:{100 * sign * nt[sel & (nt['year'] == y)]['excess'].mean():+.2f}"
        for y in sorted(nt["year"].unique())
    )
    nday = nt[sel].groupby("date").size().mean()
    print(
        f"{name:<32}{nday:>6.0f}{100 * m:>+9.3f}{t:>6.1f}{100 * raw.mean():>+8.3f}{100 * (raw.mean() - COST):>+8.3f}  {yrs}"
    )


report("ALL stocks (baseline)", nt["excess"].notna())
for tag, col in (("MODEL", "p"), ("CONTROL(shuffled)", "p_ctrl")):
    q = nt.groupby("date")[col].rank(pct=True)
    report(f"{tag} top 10% = BUY", q > 0.9)
    report(f"{tag} top 2% = BUY", q > 0.98)
    report(f"{tag} bottom 10% = SELL(short)", q <= 0.1, short=True)
    report(f"{tag} bottom 2% = SELL(short)", q <= 0.02, short=True)
print("\nPlain rules (BUY if bullish, SELL(short) if bearish):")
for r, short in (
    ("r_breakout20", False),
    ("r_breakdown20", True),
    ("r_oversold_up", False),
    ("r_overbought", True),
    ("r_trend", False),
    ("r_bull_engulf", False),
    ("r_bear_engulf", True),
):
    report(r + (" -> SELL" if short else " -> BUY"), nt[r] == 1, short=short)

# permutation importance on a test sample (AUC drop)
samp = test.sample(min(60000, len(test)), random_state=0)
ys = (samp["excess"] > 0).astype(int)
base = roc_auc_score(ys, m_main.predict_proba(samp[FEATS])[:, 1])
imp = {}
for fcol in FEATS:
    s = samp[FEATS].copy()
    s[fcol] = rng.permutation(s[fcol].to_numpy())
    imp[fcol] = base - roc_auc_score(ys, m_main.predict_proba(s)[:, 1])
print(
    "\nTop features by AUC drop:",
    ", ".join(f"{k} {v:.4f}" for k, v in sorted(imp.items(), key=lambda kv: -kv[1])[:6]),
)


# ---------------------------------------------------------------- hold until a SELL signal (no fixed horizon)
print(
    "\n=== Hold until a sell signal: buy at the next open after a BUY signal, sell at the next open after a SELL signal ==="
)
with psycopg.connect(a.db) as _c:
    costs = Costs(_c)
print(describe(costs))
df["lo"] = np.log(df["o1"] / df.groupby("iid")["o1"].shift(1))
CI = df.groupby("date")["lo"].mean().fillna(0).cumsum()  # equal-weight market, open to open (log)
test = test.sort_values(["iid", "date"]).reset_index(drop=True)
test["q"] = test.groupby("date")["p"].rank(pct=True)
test["q_ctrl"] = test.groupby("date")["p_ctrl"].rank(pct=True)


def run_trades(name: str, buy: pd.Series, sell: pd.Series) -> None:
    rows_ = []
    for iid, g in test.groupby("iid", sort=False):
        b, s = buy.loc[g.index].to_numpy(), sell.loc[g.index].to_numpy()
        o1, dts, tu = g["o1"].to_numpy(), g["date"].to_numpy(), g["turn1"].to_numpy()
        ent = -1
        for k in range(len(g)):
            if ent < 0 and b[k]:
                ent = k
            elif ent >= 0 and s[k]:
                rows_.append((iid, ent, k, o1[ent], o1[k], dts[ent], dts[k], tu[ent], tu[k]))
                ent = -1
        if ent >= 0 and len(g) - 1 > ent:  # still open at the end: marked at the last open
            k = len(g) - 1
            rows_.append((iid, ent, k, o1[ent], o1[k], dts[ent], dts[k], tu[ent], tu[k]))
    if not rows_:
        print(f"{name:<34} no trades")
        return
    t = pd.DataFrame(rows_, columns=["iid", "e", "x", "pe", "px", "de", "dx", "te", "tx"])
    t["gross"] = t["px"] / t["pe"] - 1
    t["cost"] = vec_round_trip(
        costs, t["de"].to_numpy(), t["dx"].to_numpy(), t["te"].to_numpy(), t["tx"].to_numpy()
    )
    t["mkt"] = np.exp(CI.reindex(t["dx"]).to_numpy() - CI.reindex(t["de"]).to_numpy()) - 1
    t["net"] = t["gross"] - t["cost"]
    t["nex"] = t["net"] - t["mkt"]
    t["hold"] = t["x"] - t["e"]
    month = pd.to_datetime(t["de"]).dt.to_period("M")
    m, tt = ttest(t.groupby(month)["nex"].mean())
    yrs = " ".join(
        f"{y}:{100 * g['nex'].mean():+.2f}" for y, g in t.groupby(pd.to_datetime(t["de"]).dt.year)
    )
    print(
        f"{name:<34}{len(t):>7,}{t['hold'].mean():>7.1f}{100 * t['gross'].mean():>+8.2f}{100 * t['cost'].mean():>7.2f}{100 * t['net'].mean():>+8.2f}{100 * t['mkt'].mean():>+8.2f}{100 * t['nex'].mean():>+9.2f}{tt:>6.1f}{100 * (t['net'] > 0).mean():>7.0f}  {yrs}"
    )


print(
    f"{'strategy':<34}{'trades':>7}{'days':>7}{'gross%':>8}{'cost%':>7}{'net%':>8}{'mkt%':>8}{'net-mkt%':>9}{'t':>6}{'win%':>7}  by entry year (net-mkt %)"
)
run_trades("MODEL buy top10% / sell <50%", test["q"] >= 0.9, test["q"] <= 0.5)
run_trades("MODEL buy top10% / sell <20%", test["q"] >= 0.9, test["q"] <= 0.2)
run_trades("CONTROL buy top10% / sell <50%", test["q_ctrl"] >= 0.9, test["q_ctrl"] <= 0.5)
run_trades("RULE breakout20 / breakdown20", test["r_breakout20"] == 1, test["r_breakdown20"] == 1)
run_trades(
    "RULE uptrend start / sell below SMA50",
    (test["r_trend"] == 1) & (test["r_trend"].groupby(test["iid"]).shift(1) == 0),
    test["dist_sma50"] < 0,
)
print(
    "mkt% = equal-weight market over the same open-to-open window; net-mkt% is the trade's edge over just holding the average stock. t is across entry months."
)
