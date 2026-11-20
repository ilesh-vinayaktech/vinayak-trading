# ruff: noqa: E501
"""Study: a calibrated "chance this stock closes higher N sessions from now" from its own history, and the threshold for calling Up or Down chosen from data.

For N = 5, 10 and 20 sessions: the own-history features of algo.market.rise_odds (no market state, no other stocks), a boosted model trained on 2019 to 2021, its probabilities calibrated
(isotonic) on 2022 and 2023 (the model never saw those labels), and everything judged on 2024 onward. A gap of 2N+10 days sits between the periods. Three questions:
  1  Is "60%" really 60%? Calibration on the judged years, with and without the calibration step (the market's up-rate moved from about 53% to 47%, which shifts every chance).
  2  Which threshold? Chosen on the 2022-23 data by explicit rules, never by looking at the judged years:
       max-edge   the threshold that maximises the total excess return of the calls (n x (mean return of the calls less the mean return of all stocks)): every call above it adds edge, the next one would not
       pays       the lowest threshold at which the calls' mean return still beats a 0.5% round-trip cost
     and the same idea for Down (the chance at or under which the stock tended to fall).
  3  How did each chosen threshold do on the judged years: how many calls, on how many days, how often right, the mean return, and year by year?
usage: study_horizon_thresholds.py [--db URL]"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
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
feats = ro.features(p)
liq = ro.liquid(p)
COST = flat_cost()


def stack(mask: np.ndarray) -> np.ndarray:
    x = np.column_stack([feats[k].to_numpy()[mask] for k in ro.OWN_FEATURES]).astype("float32")
    x[~np.isfinite(x)] = np.nan
    return x


def ece(pred: np.ndarray, y: np.ndarray) -> float:
    """The average gap between what the model said and what happened, over ten bands of its chance (weighted by how many fell in each)."""
    bins = np.clip((pred * 10).astype(int), 0, 9)
    tot = 0.0
    for b in range(10):
        m = bins == b
        if m.sum() >= 200:
            tot += m.sum() * abs(pred[m].mean() - y[m].mean())
    return tot / len(pred)


for H in (5, 10, 20):
    fwd = C.shift(-H) / C - 1
    ok = (liq & ~ro._split_mask(p, splits, 70, H) & fwd.notna()).to_numpy()
    day = np.nonzero(ok)[0]
    dates = idx[day]
    X = stack(ok)
    r = fwd.to_numpy()[ok]
    y = (r > 0).astype(np.int8)
    gap = np.timedelta64(2 * H + 10, "D")
    tr = dates < (np.datetime64("2022-01-01") - gap)
    va = (dates >= np.datetime64("2022-01-01")) & (dates < (np.datetime64("2024-01-01") - gap))
    te = dates >= np.datetime64("2024-01-01")
    years = pd.DatetimeIndex(dates).year.to_numpy()
    rows = np.nonzero(tr)[0][::2]
    model = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=800,
        l2_regularization=5.0,
        random_state=0,
    ).fit(X[rows], y[rows])
    raw_va, raw_te = model.predict_proba(X[va])[:, 1], model.predict_proba(X[te])[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip").fit(raw_va, y[va])
    p_va, p_te = iso.predict(raw_va), iso.predict(raw_te)
    print(f"\n==================== {H} sessions ahead ====================")
    print(
        f"rows: train {tr.sum():,} (2019-21), calibrate/choose {va.sum():,} (2022-23), judge {te.sum():,} (2024 on).  Up-rate: train {100 * y[tr].mean():.1f}%, 2022-23 {100 * y[va].mean():.1f}%, judged {100 * y[te].mean():.1f}%"
    )
    print(
        f"AUC on the judged years {roc_auc_score(y[te], raw_te):.4f}.  Calibration error: uncalibrated {100 * ece(raw_te, y[te]):.2f} pts, calibrated {100 * ece(p_te, y[te]):.2f} pts"
    )
    print("is 'N%' really N%?  the judged years, by the calibrated chance:")
    for lo, hi in (
        (0, 0.35),
        (0.35, 0.40),
        (0.40, 0.45),
        (0.45, 0.50),
        (0.50, 0.55),
        (0.55, 0.60),
        (0.60, 0.65),
        (0.65, 0.70),
        (0.70, 1.01),
    ):
        m = (p_te >= lo) & (p_te < hi)
        if m.sum() >= 200:
            print(
                f"   said {lo:.2f}-{min(hi, 1):.2f}: {m.sum():>8,} cases on {len(np.unique(day[te][m])):>3} days, rose {100 * y[te][m].mean():5.1f}% (said {100 * p_te[m].mean():5.1f}%), mean {H}-session move {100 * r[te][m].mean():+.2f}%"
            )

    base_va, base_te = r[va].mean(), r[te].mean()

    def best(
        side: str, p_va: np.ndarray, r_va: np.ndarray, base_va: float
    ) -> tuple[float | None, float | None]:
        """The threshold chosen on 2022-23 only: (the one maximising the calls' total excess return, the one at which the calls first pay a 0.5% cost)."""
        grid = np.arange(0.50, 0.81, 0.01) if side == "up" else np.arange(0.20, 0.50, 0.01)
        found = []
        for t in grid:
            sel = p_va >= t if side == "up" else p_va <= t
            n = int(sel.sum())
            if n < 1000:
                continue
            mret = r_va[sel].mean()
            edge = n * ((mret - base_va) if side == "up" else (base_va - mret))
            pays = (mret - COST > 0) if side == "up" else (-mret - COST > 0)
            found.append((float(t), n, edge, bool(pays)))
        if not found:
            return None, None
        t_edge = max(found, key=lambda x: x[2])[0]
        paying = [x[0] for x in found if x[3]]
        t_pays = (min(paying) if side == "up" else max(paying)) if paying else None
        return t_edge, t_pays

    for side in ("up", "down"):
        t_edge, t_pays = best(side, p_va, r[va], base_va)
        print(
            f"{side.upper()} threshold chosen on 2022-23: max-edge {t_edge}, pays-after-real-cost {t_pays}"
        )
        for label, t in (("max-edge", t_edge), ("pays", t_pays)):
            if t is None:
                continue
            for part_name, part, pp, base in (
                ("2022-23", va, p_va, base_va),
                ("judged 2024+", te, p_te, base_te),
            ):
                sel = pp >= t if side == "up" else pp <= t
                if sel.sum() < 100:
                    print(f"   {label:<9} t={t:.2f} {part_name:<13} too few calls")
                    continue
                rr, yy = r[part][sel], y[part][sel]
                right = yy.mean() if side == "up" else 1 - yy.mean()
                print(
                    f"   {label:<9} t={t:.2f} {part_name:<13} {int(sel.sum()):>8,} calls ({100 * sel.mean():4.1f}% of days) on {len(np.unique(day[part][sel])):>3} days: right {100 * right:5.1f}%, mean move {100 * rr.mean():+.2f}% (all stocks {100 * base:+.2f}%)"
                )
            if label == "max-edge":
                sel_te = p_te >= t if side == "up" else p_te <= t
                parts = []
                for yr in (2024, 2025, 2026):
                    m = sel_te & (years[te] == yr)
                    if m.sum():
                        right = y[te][m].mean() if side == "up" else 1 - y[te][m].mean()
                        parts.append(f"{yr}: {100 * right:.1f}% right (n={int(m.sum()):,})")
                print(f"             by year, judged: {', '.join(parts)}")
