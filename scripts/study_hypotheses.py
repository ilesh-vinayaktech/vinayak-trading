# ruff: noqa: E501
"""Check the claims of an outside review of the rise-odds approach, one by one, on the data this project really has (NSE daily bars since 2019-10, the Nifty 500's 20 sectors,
the S&P 500, Nasdaq and US VIX indices; no US stocks, no intraday history). Same discipline as before: train to 2022, judge only on 2024 onward with a gap, and every high-precision
tail is shown with the number of different days it comes from and its lift over the same day's base rate (a tail on a few market-wide days is not stock selection).
  1  Do boosted trees beat a plain logistic regression and a random forest on the same 21 features?            (target A: beats the median stock over 5 sessions)
  2  Does adding the S&P 500 / Nasdaq / US VIX (as known before the Indian close) help?
  3  Is "beats its own sector" a more tractable target than "beats the market"?                               (the 497 stocks with a sector)
  4  Is a significant DOWNSIDE (low at least 6% under today's close within 10 sessions) forecastable, and by more than past volatility alone says?
  5  After costs, what is left of the top and bottom picks?
usage: study_hypotheses.py [--db URL]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from algo.market import rise_odds as ro

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

with psycopg.connect(a.db) as conn:
    last = conn.execute(
        "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE source='nse' AND series='EQ'"
    ).fetchone()[0]
    p = ro.load_panel(conn, ro.HISTORY_FROM, last)
    splits = ro.load_splits(conn)
    sector_rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id) instrument_id, sector FROM instrument_sector ORDER BY instrument_id, effective_from DESC"
    ).fetchall()
    us_rows = conn.execute(
        "SELECT day, symbol, close::float8 FROM global_daily WHERE symbol IN ('SP500','NASDAQ','VIXUS') ORDER BY day"
    ).fetchall()
sector = {int(i): s for i, s in sector_rows}
C, H, L = p.close, p.high, p.low
T, S = C.shape
idx = np.array(C.index, dtype="datetime64[D]")
feats = ro.features(p)
ret1 = C.pct_change()
feats["vol20"] = ret1.rolling(20, min_periods=10).std() * 100
feats["atr14"] = (H - L).rolling(14, min_periods=14).mean() / C * 100
feats["vol60"] = ret1.rolling(60, min_periods=30).std() * 100

# sector-relative versions of a few features (only the Nifty 500 stocks have a sector; the rest stay missing)
groups: dict[str, list[int]] = {}
for k, c in enumerate(C.columns):
    if int(c) in sector:
        groups.setdefault(sector[int(c)], []).append(k)


def sector_median(f: pd.DataFrame) -> np.ndarray:
    arr = f.to_numpy()
    out = np.full(arr.shape, np.nan, dtype="float32")
    for members in groups.values():
        out[:, members] = np.nanmedian(arr[:, members], axis=1)[:, None]
    return out


REL = ("r5", "r20", "r60", "dpct5", "vr5", "g50")
for name in REL:
    f = feats[name]
    feats[f"{name}_sec"] = pd.DataFrame(
        f.to_numpy() - sector_median(f), index=C.index, columns=C.columns
    )

# the US indices as known before the Indian close: the last US session strictly before each Indian day
us = pd.DataFrame(us_rows, columns=["day", "symbol", "close"]).pivot(
    index="day", columns="symbol", values="close"
)
us.index = pd.to_datetime(us.index)
us_feat = pd.DataFrame(
    {
        "sp_r1": us["SP500"].pct_change(),
        "nq_r1": us["NASDAQ"].pct_change(),
        "sp_r5": us["SP500"].pct_change(5),
        "vix": us["VIXUS"],
        "vix_chg": us["VIXUS"].pct_change(),
    }
)
pos = (
    np.searchsorted(np.array(us.index, dtype="datetime64[D]"), idx, side="left") - 1
)  # strictly before the Indian day
for name in us_feat:
    v = np.where(pos >= 0, us_feat[name].to_numpy()[np.clip(pos, 0, None)], np.nan).astype(
        "float32"
    )
    feats[f"us_{name}"] = pd.DataFrame(
        np.broadcast_to(v[:, None], (T, S)), index=C.index, columns=C.columns
    )

BASE = list(ro.FEATURES)
US = [f"us_{n}" for n in us_feat]
SEC = [f"{n}_sec" for n in REL]
VOLS = ["vol20", "atr14", "vol60"]

# ---- rows and targets ----
fwd5 = C.shift(-5) / C - 1
ok = ro.liquid(p) & ~ro._split_mask(p, splits, 70, 10) & fwd5.notna() & C.shift(-10).notna()
liq = ok.to_numpy()
day = np.nonzero(liq)[0]
dates = idx[day]
n = int(liq.sum())
ex5 = ro.excess(p, splits).to_numpy()[liq]
sec_fwd = sector_median(fwd5.where(ok))
fwd5_f = fwd5.to_numpy()[liq]
ex_sec = fwd5_f - sec_fwd[liq]
has_sec = np.zeros((T, S), dtype=bool)
for members in groups.values():
    has_sec[:, members] = True
has_sec = has_sec[liq]
dd10 = (L.rolling(10).min().shift(-10) / C - 1).to_numpy()[
    liq
]  # the worst low of the next 10 sessions against today's close
up10 = (H.rolling(10).max().shift(-10) / C - 1).to_numpy()[liq]


def stack(names: list[str]) -> np.ndarray:
    x = np.column_stack([feats[k].to_numpy()[liq] for k in names]).astype("float32")
    x[~np.isfinite(x)] = np.nan  # a division by zero is a missing figure, not a huge one
    return x


gap = np.timedelta64(30, "D")
tr = dates < (np.datetime64("2023-01-01") - gap)
te = dates >= np.datetime64("2024-01-01")
print(
    f"{n:,} liquid stock-days; train {tr.sum():,} (to 2022), judged on {te.sum():,} (2024 onward); {len(groups)} sectors, {int(has_sec[te].sum()):,} judged rows have a sector\n"
)


def hgb() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=800,
        l2_regularization=5.0,
        random_state=0,
    )


def tails(
    score: np.ndarray, y: np.ndarray, d: np.ndarray, covs: tuple[float, ...] = (0.01, 0.05, 0.25)
) -> None:
    day_base = pd.Series(y.astype(float)).groupby(d).transform("mean").to_numpy()
    order = np.argsort(-score)
    for c in covs:
        k = max(1, int(c * len(score)))
        t, b = order[:k], order[-k:]
        print(
            f"      {100 * c:>5.1f}%  top say yes: {100 * y[t].mean():5.1f}% on {len(np.unique(d[t])):>3} days (same-day lift {100 * (y[t] - day_base[t]).mean():+5.1f} pt)   bottom say no: {100 * (1 - y[b]).mean():5.1f}% (lift {100 * (day_base[b] - y[b]).mean():+5.1f} pt)"
        )


def fit_eval(
    title: str,
    model,
    X: np.ndarray,
    y: np.ndarray,
    rows_tr: np.ndarray,
    rows_te: np.ndarray,
    show_tails: bool = True,
    sub: int = 1,
) -> np.ndarray:
    t = np.nonzero(rows_tr)[0][::sub]
    model.fit(X[t], y[t])
    s = model.predict_proba(X[rows_te])[:, 1]
    print(
        f"   {title:<46} AUC {roc_auc_score(y[rows_te], s):.4f}   (base rate {100 * y[rows_te].mean():.1f}%, {rows_te.sum():,} cases)"
    )
    if show_tails:
        tails(s, y[rows_te], day[rows_te])
    return s


y_a = (ex5 > 0).astype(np.int8)
X21 = stack(BASE)

print(
    "=== 1. model bake-off, target A (beats the median stock over 5 sessions), the same 21 features"
)
logit = make_pipeline(
    SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.05, max_iter=300)
)
fit_eval("logistic regression", logit, X21, y_a, tr, te, sub=2)
rf = make_pipeline(
    SimpleImputer(strategy="median"),
    RandomForestClassifier(
        n_estimators=120,
        min_samples_leaf=400,
        max_depth=14,
        max_features="sqrt",
        n_jobs=8,
        random_state=0,
    ),
)
fit_eval("random forest", rf, X21, y_a, tr, te, sub=3)
s_a = fit_eval("gradient boosting (the product's model)", hgb(), X21, y_a, tr, te, sub=2)

print("\n=== 2. add the S&P 500 / Nasdaq / US VIX (last US session before the Indian day)")
fit_eval("boosting, 21 + 5 US features", hgb(), stack(BASE + US), y_a, tr, te, sub=2)

print(
    "\n=== 3. beats its own sector (the Nifty 500 stocks with a sector), against beats the market, same rows"
)
rows_tr, rows_te = tr & has_sec, te & has_sec
y_f = (ex_sec > 0).astype(np.int8)
fit_eval("target: beats the MARKET, 21 features", hgb(), X21, y_a, rows_tr, rows_te)
fit_eval("target: beats its SECTOR, 21 features", hgb(), X21, y_f, rows_tr, rows_te)
fit_eval(
    "target: beats its SECTOR, 21 + sector-relative",
    hgb(),
    stack(BASE + SEC),
    y_f,
    rows_tr,
    rows_te,
)

print(
    "\n=== 4. significant downside: the low of the next 10 sessions is at least 6% under today's close"
)
y_d, y_u = (dd10 <= -0.06).astype(np.int8), (up10 >= 0.06).astype(np.int8)
vol_only = make_pipeline(
    SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=1.0, max_iter=300)
)
for title, y in (("DOWNSIDE of 6% or more", y_d), ("UPSIDE of 6% or more", y_u)):
    print(f"  -- {title}")
    s_vol = fit_eval(
        "past volatility alone (vol20, atr14, vol60)",
        vol_only,
        stack(VOLS),
        y,
        tr,
        te,
        show_tails=False,
        sub=2,
    )
    s_all = fit_eval(
        "boosting, all features + volatility + US",
        hgb(),
        stack(BASE + VOLS + US),
        y,
        tr,
        te,
        show_tails=False,
        sub=2,
    )
    d = day[te]
    yt = y[te]
    day_base = pd.Series(yt.astype(float)).groupby(d).transform("mean").to_numpy()
    for c in (0.01, 0.05, 0.10):
        k = max(1, int(c * len(yt)))
        tv, tm = np.argsort(-s_vol)[:k], np.argsort(-s_all)[:k]
        print(
            f"      top {100 * c:>4.0f}% riskiest: model {100 * yt[tm].mean():5.1f}% ({len(np.unique(d[tm]))} days, same-day lift {100 * (yt[tm] - day_base[tm]).mean():+5.1f} pt)   volatility alone {100 * yt[tv].mean():5.1f}% ({len(np.unique(d[tv]))} days, lift {100 * (yt[tv] - day_base[tv]).mean():+5.1f} pt)   base {100 * yt.mean():.1f}%"
        )

print(
    "\n=== 5. costs: the 5-session return of the model's top and bottom picks (target A model), before and after an assumed round-trip cost"
)
order = np.argsort(-s_a)
r5 = fwd5_f[te]
for c in (0.01, 0.05):
    k = max(1, int(c * len(order)))
    top, bot = r5[order[:k]], r5[order[-k:]]
    print(
        f"   top {100 * c:.0f}%: mean {100 * top.mean():+.2f}% (random stock {100 * r5.mean():+.2f}%), after a 0.35% / 0.5% round trip {100 * (top.mean() - 0.0035):+.2f}% / {100 * (top.mean() - 0.005):+.2f}%;  bottom {100 * c:.0f}%: mean {100 * bot.mean():+.2f}% (a short would earn {100 * -bot.mean():+.2f}% before costs and short-selling constraints)"
    )
