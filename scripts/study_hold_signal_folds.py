# ruff: noqa: E501
"""Hold-until-sell-signal, across years, with the controls the owner's review asked for. The ORIGINAL rules of scripts/study_price_action.py, unchanged:

  model   pooled HistGradientBoostingClassifier(max_depth 4, lr 0.05, 200 iterations, min_samples_leaf 500, l2 5) on 31 OHLC-only features (the study's stock_frame, no volume),
          target = the 5-session return from the next open beats the median stock of that day. No tuning of any kind.
  signal  each day every stock's score is ranked across the day's stocks: BUY when the rank is in the top 10% (>= 0.9), SELL when it falls to <= 0.2 (the +0.27% variant) or <= 0.5.
  trade   buy at the NEXT open after a BUY signal, sell at the NEXT open after a SELL signal; no stops, no fixed horizon; a position still open at the end of the test year is marked at the last open.
Folds (rolling origin; fixed hyperparameters, so no selection year is needed; the year before each test year is a gap): test 2022 / 2023 / 2024, trained to the end of 2020 / 2021 / 2022 (the 2024 fold is the original split).
Bars only to development_end (2025-01-01 onward never read; the original run also tested on 2025-26, which is why it is repeated here).
Controls: market = the equal-weight average stock over the same open-to-open window; same-volatility = the average stock of the entry day's ATR% quintile over the window; random entries
(same stocks and holding lengths, entry dates drawn at random inside the test year, 200 draws); buy-and-hold market; the original breakout20/breakdown20 momentum rule; a capacity-limited
equal-weight portfolio (max 10 positions). Costs: the repo's DB cost schedules + slippage on every trade.
usage: study_hold_signal_folds.py [--db URL] [--start 2019-09-01] [--max-positions 10]"""

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier
from study_common import BARS, Costs, describe, vec_round_trip
from winner_v2_common import DEV_END

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--start", default="2019-09-01")
ap.add_argument("--max-positions", type=int, default=10)
ap.add_argument(
    "--dump",
    help="write the pooled MODEL buy top10% / sell <20% trades (development period) to this CSV, for the execution check",
)
ap.add_argument("--min-turnover-cr", type=float, default=5.0)
ap.add_argument(
    "--end",
    default=str(DEV_END),
    help="last bar date to load (default: the end of the development period)",
)
ap.add_argument(
    "--universe-end",
    help="the universe (median traded value, 400+ bars) is measured on bars up to this date (default: --end)",
)
ap.add_argument(
    "--folds",
    help="test folds as year:train_end:test_start:test_end,... (default: the development folds 2022, 2023, 2024)",
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
H, SEED, T0 = 5, 0, time.time()
DEFAULT_FOLDS = "2022:2020-12-31:2022-01-01:2022-12-31,2023:2021-12-31:2023-01-01:2023-12-31,2024:2022-12-31:2024-01-01:2024-12-31"
FOLDS = [tuple(x.split(":")) for x in (a.folds or DEFAULT_FOLDS).split(",")]
UNIVERSE_END = pd.Timestamp(a.universe_end or a.end)

with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= %s AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= %s ORDER BY instrument_id, ts, dataset_version DESC",
        (a.start, a.end),
    ).fetchall()
    costs = Costs(conn)
bars = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
del rows
bars["d"] = pd.to_datetime(bars["d"])
ref = bars[bars["d"] <= UNIVERSE_END]  # the universe is chosen on data up to UNIVERSE_END only
turn = (ref["c"] * ref["v"] / 1e7).groupby(ref["iid"]).median()
nb = ref.groupby("iid").size()
ids = [int(i) for i in nb.index[(nb >= 400) & (turn.reindex(nb.index) >= a.min_turnover_cr)]]
print(
    f"{len(ids)} liquid stocks (median traded value >= Rs {a.min_turnover_cr:g} cr, 400+ bars) from {a.start} to {a.end} (universe measured to {UNIVERSE_END.date()}); {describe(costs)}"
)


def stock_frame(iid: int, d: pd.DataFrame) -> pd.DataFrame:
    """The 31 OHLC-only features of scripts/study_price_action.py (default flags), unchanged, plus what the trade simulation needs."""
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
        f[f"ret{k}"] = np.log(c / c.shift(k)) / (vol20 * np.sqrt(k))
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
    f["fwd"] = c.shift(-H) / o.shift(-1) - 1
    f["o1"], f["turn1"] = o.shift(-1), (c * d["v"]).shift(-1)
    f["hh"], f["ll"] = h, lo
    f["iid"] = iid
    return f


df = (
    pd.concat([stock_frame(i, g) for i, g in bars[bars["iid"].isin(ids)].groupby("iid")])
    .reset_index()
    .rename(columns={"d": "date"})
)
del bars
df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["fwd", "ret60", "dist_sma200", "pos252"])
df["excess"] = df["fwd"] - df.groupby("date")["fwd"].transform("median")
df = (
    df[df.groupby("date")["iid"].transform("size") >= 30]
    .sort_values(["iid", "date"])
    .reset_index(drop=True)
)
NOTFEAT = {"date", "iid", "fwd", "excess", "o1", "turn1", "hh", "ll"}
FEATS = [c for c in df.columns if c not in NOTFEAT]
assert len(FEATS) == 31, len(FEATS)
# the equal-weight market and the volatility-quintile averages, open to open (log), cumulated along dates
df["lo"] = np.log(df["o1"] / df.groupby("iid")["o1"].shift(1))
df["vq_now"] = (
    (df.groupby("date")["atr_pct"].rank(pct=True) * 5).clip(upper=4.999).fillna(0).astype(int)
)
df["vq_prev"] = df.groupby("iid")["vq_now"].shift(1)
dates = np.sort(df["date"].unique())
df["di"] = df["date"].map({d: i for i, d in enumerate(dates)})
CI = df.groupby("di")["lo"].mean().reindex(range(len(dates))).fillna(0).cumsum().to_numpy()
CQ = (
    df.groupby(["di", "vq_prev"])["lo"]
    .mean()
    .unstack()
    .reindex(index=range(len(dates)), columns=[0.0, 1.0, 2.0, 3.0, 4.0])
    .fillna(0)
    .cumsum()
    .to_numpy()
)
daily_mkt = pd.Series(
    np.expm1(np.diff(CI, prepend=0.0)), index=dates
)  # equal-weight average stock, open to open
print(
    f"{len(df):,} stock-days, {df['iid'].nunique()} stocks, {len(dates)} sessions; features {len(FEATS)}; {time.time() - T0:.0f}s\n"
)


def boot(
    x: np.ndarray, d: np.ndarray, block: int = 15, reps: int = 1000
) -> tuple[float, float, float]:
    """Mean of per-entry-date means with a 15-day moving-block bootstrap over entry dates."""
    s = pd.Series(x).groupby(d).mean().sort_index().to_numpy()
    n = len(s)
    starts = np.random.default_rng(SEED).integers(0, n, (reps, -(-n // block)))
    est = s[((starts[:, :, None] + np.arange(block)) % n).reshape(reps, -1)[:, :n]].mean(1)
    return float(s.mean()), float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))


def fmt(b: tuple[float, float, float]) -> str:
    return f"{100 * b[0]:+.2f} [{100 * b[1]:+.2f},{100 * b[2]:+.2f}]"


def trades_for(test: pd.DataFrame, buy: np.ndarray, sell: np.ndarray) -> pd.DataFrame:
    """The original state machine per stock: buy at the next open after a BUY signal, sell at the next open after a SELL signal; open at the end -> marked at the last open."""
    rec = []
    for iid, g in test.groupby("iid", sort=False):
        ix = g.index.to_numpy()
        b, s = buy[ix], sell[ix]
        o1, di, tu, hh, ll, vq = (
            g["o1"].to_numpy(),
            g["di"].to_numpy(),
            g["turn1"].to_numpy(),
            g["hh"].to_numpy(),
            g["ll"].to_numpy(),
            g["vq_now"].to_numpy(),
        )
        ent = -1
        spans = []
        for k in range(len(g)):
            if ent < 0 and b[k]:
                ent = k
            elif ent >= 0 and s[k]:
                spans.append((ent, k))
                ent = -1
        if ent >= 0 and len(g) - 1 > ent:
            spans.append((ent, len(g) - 1))
        for e, x in spans:
            rec.append(
                (
                    iid,
                    e,
                    x,
                    o1[e],
                    o1[x],
                    di[e],
                    di[x],
                    tu[e],
                    tu[x],
                    hh[e + 1 : x + 1].max() / o1[e] - 1,
                    ll[e + 1 : x + 1].min() / o1[e] - 1,
                    vq[e],
                )
            )
    t = pd.DataFrame(
        rec, columns=["iid", "e", "x", "pe", "px", "de", "dx", "te", "tx", "mfe", "mae", "vq"]
    )
    if t.empty:
        return t
    t["gross"] = t["px"] / t["pe"] - 1
    t["cost"] = vec_round_trip(
        costs,
        dates[t["de"].to_numpy()],
        dates[t["dx"].to_numpy()],
        t["te"].to_numpy(),
        t["tx"].to_numpy(),
    )
    t["net"] = t["gross"] - t["cost"]
    t["mkt"] = np.exp(CI[t["dx"].to_numpy()] - CI[t["de"].to_numpy()]) - 1
    t["vm"] = (
        np.exp(
            CQ[t["dx"].to_numpy(), t["vq"].to_numpy()] - CQ[t["de"].to_numpy(), t["vq"].to_numpy()]
        )
        - 1
    )
    t["hold"] = t["x"] - t["e"]
    return t


def summarize(label: str, t: pd.DataFrame) -> None:
    if t.empty:
        print(f"{label:<30} no trades")
        return
    bm, bv = (
        boot((t["net"] - t["mkt"]).to_numpy(), t["de"].to_numpy()),
        boot((t["net"] - t["vm"]).to_numpy(), t["de"].to_numpy()),
    )
    win, loss = t.loc[t["net"] > 0, "net"], t.loc[t["net"] <= 0, "net"]
    pf = win.sum() / max(-loss.sum(), 1e-12)
    print(
        f"{label:<30}{len(t):>6,}{t['hold'].mean():>6.1f}{int(t['hold'].max()):>5}{100 * t['gross'].mean():>+7.2f}{100 * t['net'].mean():>+7.2f} | {fmt(bm):^22} | {fmt(bv):^22} | {100 * (t['net'] > 0).mean():>4.0f}% {pf:>5.2f} {100 * win.mean():>+6.2f}/{100 * loss.mean():+.2f} | {100 * t['mfe'].mean():>+6.1f}/{100 * t['mae'].mean():+.1f}"
    )


def random_entry_null(
    t: pd.DataFrame, test: pd.DataFrame, draws: int = 200
) -> tuple[float, float, float]:
    """Same stocks, same holding lengths and costs, entry dates drawn at random inside the test year: the mean (net - market) a trade gets with no signal."""
    rng = np.random.default_rng(SEED)
    per = {iid: (g["o1"].to_numpy(), g["di"].to_numpy()) for iid, g in test.groupby("iid")}
    means = np.empty(draws)
    for r in range(draws):
        acc = []
        for iid, hold, cost in zip(t["iid"], t["hold"], t["cost"], strict=True):
            o1, di = per[iid]
            n = len(o1)
            if n <= hold + 1:
                continue
            e = int(rng.integers(0, n - hold - 1))
            acc.append(o1[e + hold] / o1[e] - 1 - cost - (np.exp(CI[di[e + hold]] - CI[di[e]]) - 1))
        means[r] = np.mean(acc)
    return float(means.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def portfolio(test: pd.DataFrame, q: np.ndarray, sell_lvl: float, nmax: int) -> pd.DataFrame:
    """Equal-weight portfolio of at most nmax positions (1/nmax of capital each), entries by highest rank first, no duplicates, the same signals, costs deducted on the trade day."""
    d_t, iid_t, tu = test["di"].to_numpy(), test["iid"].to_numpy(), test["turn1"].to_numpy()
    ret_row = (test["o1"] / test.groupby("iid")["o1"].shift(1) - 1).to_numpy()
    held: set[int] = set()
    out: dict[int, tuple[float, float]] = {}
    w = 1.0 / nmax
    for d in np.unique(d_t):
        rows = np.flatnonzero(d_t == d)
        rmap = {iid_t[i]: i for i in rows}
        day_ret = sum(
            w * np.nan_to_num(ret_row[rmap[s]]) for s in held if s in rmap
        )  # the interval open(d) -> open(d+1) of the positions bought at open(d) or earlier
        cost, day = 0.0, pd.Timestamp(dates[d]).date()
        for s in [s for s in held if s in rmap and q[rmap[s]] <= sell_lvl]:
            cost += w * (costs.charges(day, "SELL") + costs.slip(tu[rmap[s]]))
            held.discard(s)
        for i in sorted(
            (i for i in rows if q[i] >= 0.9 and iid_t[i] not in held), key=lambda i: -q[i]
        )[: nmax - len(held)]:
            cost += w * (costs.charges(day, "BUY") + costs.slip(tu[i]))
            held.add(iid_t[i])
        out[d] = (day_ret - cost, len(held) / nmax)
    s = pd.DataFrame(out, index=["ret", "exposure"]).T
    s.index = dates[s.index.to_numpy()]
    return s


HDR = f"{'':<30}{'trades':>6}{'hold':>6}{'max':>5}{'gross':>7}{'net':>7} | {'net-market [95% CI]':^22} | {'net-same-vol [95% CI]':^22} | {'win':>5} {'PF':>5} {'avg win/loss':>13} | {'MFE/MAE':>12}"
SENS = [(0.9, 0.1), (0.9, 0.2), (0.9, 0.3), (0.9, 0.4), (0.9, 0.5), (0.8, 0.2), (0.95, 0.2)]
SENS_T: dict[tuple[float, float], list[pd.DataFrame]] = {}
ALLT: dict[str, list[pd.DataFrame]] = {}
PORT: list[pd.DataFrame] = []
for yr, tr_end, t0, t1 in FOLDS:
    tr = df[df["date"] <= pd.Timestamp(tr_end)]
    test = df[(df["date"] >= pd.Timestamp(t0)) & (df["date"] <= pd.Timestamp(t1))].reset_index(
        drop=True
    )
    mdl = HistGradientBoostingClassifier(
        max_depth=4,
        learning_rate=0.05,
        max_iter=200,
        min_samples_leaf=500,
        l2_regularization=5.0,
        random_state=SEED,
    ).fit(tr[FEATS], (tr["excess"] > 0).astype(int))
    test["q"] = pd.Series(mdl.predict_proba(test[FEATS])[:, 1]).groupby(test["date"]).rank(pct=True)
    print(
        f"=== test {yr}: trained on {len(tr):,} rows to {tr_end} (from {tr['date'].min().date()}), tested on {len(test):,} rows; equal-weight market over the year {100 * (np.exp(CI[test['di'].max()] - CI[test['di'].min()]) - 1):+.1f}%; {time.time() - T0:.0f}s"
    )
    print(HDR)
    qv = test["q"].to_numpy()
    sets = {
        "MODEL buy top10% / sell <20%": (qv >= 0.9, qv <= 0.2),
        "MODEL buy top10% / sell <50%": (qv >= 0.9, qv <= 0.5),
        "RULE breakout20 / breakdown20": (
            test["r_breakout20"].to_numpy() == 1,
            test["r_breakdown20"].to_numpy() == 1,
        ),
    }
    for nm, (bsig, ssig) in sets.items():
        t = trades_for(test, bsig, ssig)
        summarize(nm, t)
        ALLT.setdefault(nm, []).append(t)
        if nm == "MODEL buy top10% / sell <20%" and not t.empty:
            nl, lo_, hi_ = random_entry_null(t, test)
            obs = float((t["net"] - t["mkt"]).mean())
            print(
                f"{'  random entries, same stocks/holds':<30}{'':>29} | {fmt((nl, lo_, hi_)):^22} | strategy {100 * obs:+.2f}: {'ABOVE' if obs > hi_ else 'inside'} the random-entry range"
            )
    p20 = portfolio(test, qv, 0.2, a.max_positions)
    for bq_, sq_ in SENS:
        SENS_T.setdefault((bq_, sq_), []).append(trades_for(test, qv >= bq_, qv <= sq_))
    PORT.append(p20)
    print(
        f"  portfolio (max {a.max_positions} positions, sell <20%): return {100 * ((1 + p20['ret']).prod() - 1):+.1f}%, avg exposure {100 * p20['exposure'].mean():.0f}%, market buy&hold same dates {100 * ((1 + daily_mkt.reindex(p20.index)).prod() - 1):+.1f}%\n"
    )

print(
    f"=== POOLED over test years {FOLDS[0][0]}-{FOLDS[-1][0]} (the year-by-year rows above are the consistency check; no parameter was tuned on any test year)"
)
print(HDR)
for nm, lst in ALLT.items():
    pooled = pd.concat([t for t in lst if not t.empty])
    summarize(nm, pooled)
    byy = " | ".join(
        f"{fy[0]}: {100 * float((t['net'] - t['mkt']).mean()):+.2f}/{100 * float((t['net'] - t['vm']).mean()):+.2f}"
        for fy, t in zip(FOLDS, lst, strict=True)
        if not t.empty
    )
    print(f"{'  by year net-mkt / net-same-vol':<30}{byy}")
if len(FOLDS) == 3:
    m_early = pd.concat([t for t in ALLT["MODEL buy top10% / sell <20%"][:2] if not t.empty])
    print(
        "\nPOOLED 2022-2023 ONLY (years the sell <20% choice never saw: that variant was picked after the original run had tested 2024-26):"
    )
    print(HDR)
    summarize("MODEL buy top10% / sell <20%", m_early)
print(
    f"\nSENSITIVITY, pooled {FOLDS[0][0]}-{FOLDS[-1][0]}, net-market per trade [95% CI]; reported, not selected from (every cell is a pre-existing variant of the one rule):"
)
print(
    f"{'buy rank >= / sell rank <=':<28}{'trades':>8}{'hold':>6}{'net':>8} | {'net-market [95% CI]':^22} | by year 2022 / 2023 / 2024"
)
for key, lst in SENS_T.items():
    pooled_s = pd.concat([t for t in lst if not t.empty])
    b_ = boot((pooled_s["net"] - pooled_s["mkt"]).to_numpy(), pooled_s["de"].to_numpy())
    yrs_ = " / ".join(
        f"{100 * float((t['net'] - t['mkt']).mean()):+.2f}" if not t.empty else "n/a" for t in lst
    )
    print(
        f"{key[0]:.2f} / {key[1]:.2f}{'':<17}{len(pooled_s):>8,}{pooled_s['hold'].mean():>6.1f}{100 * pooled_s['net'].mean():>+8.2f} | {fmt(b_):^22} | {yrs_}"
    )
m20 = pd.concat([t for t in ALLT["MODEL buy top10% / sell <20%"] if not t.empty])
terc = pd.qcut(m20["te"], 3, labels=["low", "mid", "high"])
print("\nliquidity terciles (entry-day traded value), MODEL buy top10% / sell <20%:")
for b in ("low", "mid", "high"):
    s = m20[terc == b]
    print(
        f"  {b:<5} n {len(s):,}, net-market {100 * float((s['net'] - s['mkt']).mean()):+.2f}%, net-same-vol {100 * float((s['net'] - s['vm']).mean()):+.2f}%, mean cost {100 * s['cost'].mean():.2f}%"
    )

pp = pd.concat(PORT)
eq = (1 + pp["ret"]).cumprod()
bm_ = daily_mkt.reindex(pp.index)
beq = (1 + bm_).cumprod()
print(
    f"\nPORTFOLIO pooled {FOLDS[0][0]}-{FOLDS[-1][0]} (max {a.max_positions} equal-weight positions, sell <20%, after costs): annualised {100 * (eq.iloc[-1] ** (252 / len(pp)) - 1):+.1f}%, Sharpe {pp['ret'].mean() / pp['ret'].std() * np.sqrt(252):.2f}, max drawdown {100 * (eq / eq.cummax() - 1).min():.1f}%, average exposure {100 * pp['exposure'].mean():.0f}%"
)
print(
    f"  market buy-and-hold (equal-weight liquid stocks), same days: annualised {100 * (beq.iloc[-1] ** (252 / len(bm_)) - 1):+.1f}%, Sharpe {bm_.mean() / bm_.std() * np.sqrt(252):.2f}, max drawdown {100 * (beq / beq.cummax() - 1).min():.1f}%"
)
print(
    f"  return per unit of invested capital (daily portfolio return / exposure), annualised {100 * ((1 + pp['ret'].mean() / pp['exposure'].mean()) ** 252 - 1):+.1f}%"
)
if a.dump:
    dump = pd.concat([t for t in ALLT["MODEL buy top10% / sell <20%"] if not t.empty]).copy()
    dump["signal_date"], dump["exit_signal_date"] = (
        dates[dump["de"].to_numpy()],
        dates[dump["dx"].to_numpy()],
    )
    dump["exec_date"], dump["exit_exec_date"] = (
        dates[np.minimum(dump["de"].to_numpy() + 1, len(dates) - 1)],
        dates[np.minimum(dump["dx"].to_numpy() + 1, len(dates) - 1)],
    )
    dump[
        [
            "iid",
            "signal_date",
            "exec_date",
            "exit_signal_date",
            "exit_exec_date",
            "pe",
            "px",
            "te",
            "tx",
            "hold",
            "gross",
            "cost",
            "net",
            "mkt",
        ]
    ].to_csv(a.dump, index=False)
    print(f"trades written to {a.dump} ({len(dump):,})")
print(f"\ntotal {time.time() - T0:.0f}s")
