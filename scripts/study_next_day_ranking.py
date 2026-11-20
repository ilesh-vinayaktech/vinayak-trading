# ruff: noqa: E501
"""Study: can the rise-odds model be pointed at the NEXT session (horizon 1) and rank stocks usefully?

Two models, as in rise_odds.py: 'rel' (beats the median stock tomorrow) and 'up' (closes higher tomorrow), each with its own feature set and again with market-state features added
(the day's median return, the 5-day median return, the share of stocks up). Walk-forward by year: a model trained on rows before Jan 1 of the year scores that year. Judged ONLY on the
development years 2022, 2023, 2024 (config/research_holdout.json: 2025 onward is protected and is not read here).

Each daily top-15 / bottom-15 is judged on two outcomes: close-to-close (what the panel would have claimed; it assumes buying at the very close that made the signal) and next-open to
next-close (what a buyer who sees the signal after the close can really get, on the next day's candle). The test: the top-15 must beat the bottom-15 on BOTH outcomes, in each year, with the
day-clustered t-statistic of the top-minus-bottom spread above 2.
usage: study_next_day_ranking.py [--db URL]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, use_kite_panel  # noqa: E402,I001

from algo.market import rise_odds as ro

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
DEV_END = pd.Timestamp("2024-12-31").date()
YEARS = (2022, 2023, 2024)
TOP = 15

use_kite_panel(ro)  # Kite adjusted bars, not the NSE raw panel + split mask
with psycopg.connect(a.db) as conn:
    p = ro.load_panel(conn, ro.HISTORY_FROM, DEV_END)
    splits = ro.load_splits(conn)
    rows = conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8"
        f" FROM {BARS} WHERE source='kite' AND ts >= %s::date AND ts < %s::date + 1 ORDER BY instrument_id, ts, dataset_version DESC",
        (ro.HISTORY_FROM, DEV_END),
    ).fetchall()
O = (  # noqa: E741
    pd.DataFrame(rows, columns=["iid", "d", "o"])
    .pivot(index="d", columns="iid", values="o")
    .reindex(index=p.close.index, columns=p.close.columns)
    .astype("float32")
)
C = p.close
idx = np.array(C.index, dtype="datetime64[D]")
feats = ro.features(p)
r1 = C.pct_change()
liq = ro.liquid(p) & ~ro._split_mask(p, splits, 70, 1)
mkt = {
    "m_r1": r1.where(liq).median(axis=1),
    "m_r5": (C / C.shift(5) - 1).where(liq).median(axis=1),
    "m_up": (r1 > 0).where(liq).mean(axis=1),
}
for k, s in mkt.items():
    feats[k] = pd.DataFrame(
        np.repeat(s.to_numpy()[:, None], C.shape[1], axis=1), index=C.index, columns=C.columns
    ).astype("float32")

# outcomes known after day t: close-to-close, and next open to next close
cc = (C.shift(-1) / C - 1).where(liq)
oc = (C.shift(-1) / O.shift(-1) - 1).where(liq & O.shift(-1).notna())
cc_ex = cc.sub(cc.median(axis=1), axis=0)
oc_ex = oc.sub(oc.median(axis=1), axis=0)

SETS = {
    ("rel", "stock"): ro.FEATURES,
    ("rel", "stock+mkt"): (*ro.FEATURES, "m_r1", "m_r5", "m_up"),
    ("up", "stock"): ro.OWN_FEATURES,
    ("up", "stock+mkt"): (*ro.OWN_FEATURES, "m_r1", "m_r5", "m_up"),
}


def stack(where: pd.DataFrame, names: tuple[str, ...]):
    X, di, si = ro._stack(feats, where, names)
    keep = ~np.isnan(X).all(axis=1)
    return X[keep], di[keep], si[keep]


def spread_stats(prob: pd.DataFrame, out: pd.DataFrame, day_mask: np.ndarray) -> dict[str, float]:
    """Daily mean of `out` for the top/bottom TOP stocks by prob, the all-stock mean, and the day-clustered t of top - bottom."""
    pr, ou = prob[day_mask], out[day_mask]
    rk_hi = pr.rank(axis=1, ascending=False, method="first")
    rk_lo = pr.rank(axis=1, ascending=True, method="first")
    ok = pr.notna() & ou.notna()
    top = ou.where((rk_hi <= TOP) & ok).mean(axis=1)
    bot = ou.where((rk_lo <= TOP) & ok).mean(axis=1)
    base = ou.where(ok).mean(axis=1)
    sp = (top - bot).dropna()
    t = float(sp.mean() / (sp.std() / np.sqrt(len(sp)))) if len(sp) > 2 else float("nan")
    return {
        "top": float(top.mean()),
        "bot": float(bot.mean()),
        "base": float(base.mean()),
        "t": t,
        "n": len(sp),
    }


for kind in ("rel", "up"):
    tgt_ex = cc_ex if kind == "rel" else cc
    for fs_name in ("stock", "stock+mkt"):
        names = SETS[(kind, fs_name)]
        print(f"\n=== {kind} / {fs_name} ===", flush=True)
        for yr in YEARS:
            start = np.datetime64(f"{yr}-01-01")
            cutoff = start - np.timedelta64(12, "D")
            early = idx < cutoff
            wt = tgt_ex.notna() & pd.DataFrame(
                np.broadcast_to(early[:, None], C.shape), index=C.index, columns=C.columns
            )
            X, di, si = stack(wt, names)
            y = (tgt_ex.to_numpy()[di, si] > 0).astype(np.int8)
            model = ro.fit(X, y)
            inyr = (idx >= start) & (idx < np.datetime64(f"{yr + 1}-01-01"))
            ws = (
                liq
                & feats["r1"].notna()
                & pd.DataFrame(
                    np.broadcast_to(inyr[:, None], C.shape), index=C.index, columns=C.columns
                )
            )
            Xs, ds, ss = stack(ws, names)
            pm = np.full(C.shape, np.nan, dtype="float32")
            pm[ds, ss] = model.predict_proba(Xs)[:, 1]
            prob = pd.DataFrame(pm, index=C.index, columns=C.columns)
            for label, out in (
                ("close-to-close", cc if kind == "up" else cc_ex),
                ("open-to-close", oc if kind == "up" else oc_ex),
            ):
                s = spread_stats(prob, out, inyr)
                ic = prob[inyr].corrwith(out[inyr], axis=1, method="spearman").dropna()
                print(
                    f"{yr} {label:15s} top15 {s['top'] * 100:+.3f}%  bottom15 {s['bot'] * 100:+.3f}%  all {s['base'] * 100:+.3f}%  spread t={s['t']:+.2f} (days {s['n']})  IC {ic.mean():+.4f}",
                    flush=True,
                )
            if kind == "up":
                up = (cc[inyr] > 0).where(cc[inyr].notna())
                hi = prob[inyr].rank(axis=1, ascending=False, method="first") <= TOP
                lo = prob[inyr].rank(axis=1, ascending=True, method="first") <= TOP
                print(
                    f"{yr} share that rose (close-to-close): top15 {up.where(hi).stack().mean():.3f}  bottom15 {up.where(lo).stack().mean():.3f}  all {up.stack().mean():.3f}",
                    flush=True,
                )
            del X, y, Xs, pm, prob
