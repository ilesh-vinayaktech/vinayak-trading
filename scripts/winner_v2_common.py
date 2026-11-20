# ruff: noqa: E501
"""The shared data of the early-large-upside experiments (V2 spec): the liquid stock-days of the DEVELOPMENT period, their labels and their features, and the V1 split.

Kite adjusted bars up to `development_end` of config/research_holdout.json only (2025-01-01 onward is never read). Universe as V1: 20-day average traded value >= Rs 5 crore.
Split as V1: train to 2022-11-30, selection 2023-01-02..2023-11-30 (trees/config are chosen here only), out-of-time 2024-01-02 on; the gaps are >= 20 sessions (asserted).
Rows are the liquid stock-days with a full 10-session window and a prior 5-session return, in (day, stock) order. `X[:, col[name]]` is a feature; `Y` holds the targets A, B10, C
(C = +10% before -5% from the next open), `OUT` the barrier outcome code (algo.research.winner_labels), `EXR` the barrier trade's exit return (NaN for an ambiguous candle)."""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS

from algo.research import winner_features as wf
from algo.research import winner_labels as wl

ROOT = Path(__file__).resolve().parent.parent
DEV_END = json.loads((ROOT / "config/research_holdout.json").read_text())["development_end"]
TR_END, VA0, VA1, TE0 = (
    pd.Timestamp("2022-11-30"),
    pd.Timestamp("2023-01-02"),
    pd.Timestamp("2023-11-30"),
    pd.Timestamp("2024-01-02"),
)
Arr = np.ndarray[Any, Any]


@dataclass
class Data:
    day_of: Arr
    iid_of: Arr
    dts: Arr
    Y: dict[str, Arr]
    OUT: Arr
    EXR: Arr
    EARLY: Arr
    tr: Arr
    va: Arr
    te: Arr
    names: list[str]
    col: dict[str, int]
    X: Arr

    @property
    def n(self) -> int:
        return len(self.day_of)


def load(db: str, min_turnover_cr: float = 5.0) -> Data:
    t0 = time.time()
    with psycopg.connect(db) as conn:
        rows = conn.execute(
            "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
            f" FROM {BARS} WHERE source='kite' AND ts >= '2019-09-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= %s ORDER BY instrument_id, ts, dataset_version DESC",
            (DEV_END,),
        ).fetchall()
    d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v", "dq"])
    del rows
    d["d"] = pd.to_datetime(d["d"])
    pv = {
        k: d.pivot(index="d", columns="iid", values=k).sort_index()
        for k in ("o", "h", "l", "c", "v", "dq")
    }
    del d
    op, hi, lo, cl, vo, dq = (pv[k].to_numpy() for k in ("o", "h", "l", "c", "v", "dq"))
    idx = pv["c"].index
    t, s = cl.shape
    liq = (
        (pv["c"] * pv["v"]).rolling(20, min_periods=15).mean() / 1e7 >= min_turnover_cr
    ).to_numpy()
    print(
        f"bars {idx[0].date()} to {idx[-1].date()} (development period only; 2025-01-01 onward not read), {s} stocks, {t} sessions"
    )

    lab = {
        n: np.zeros((t, s), dtype=bool if n in ("valid", "A", "B10", "C") else "float64")
        for n in ("valid", "A", "B10", "C", "exit_return", "outcome")
    }
    for s0 in range(0, s, 400):
        sl = slice(s0, s0 + 400)
        r = wl.winner_labels(op[:, sl], hi[:, sl], lo[:, sl], cl[:, sl])
        lab["valid"][:, sl], lab["A"][:, sl], lab["B10"][:, sl] = r.valid, r.target_a, r.target_b_10
        lab["C"][:, sl], lab["exit_return"][:, sl], lab["outcome"][:, sl] = (
            r.outcome == wl.SUCCESS,
            r.exit_return,
            r.outcome,
        )
    prior5 = np.full((t, s), np.nan)
    prior5[5:] = cl[5:] / cl[:-5] - 1
    m = liq & lab["valid"] & np.isfinite(prior5)
    day_of, iid_of = np.nonzero(m)
    dts = idx[day_of]
    tr, va, te = dts <= TR_END, (dts >= VA0) & (dts <= VA1), dts >= TE0
    gap1, gap2 = day_of[va].min() - day_of[tr].max(), day_of[te].min() - day_of[va].max()
    assert gap1 >= 20 and gap2 >= 20, (gap1, gap2)
    print(
        f"{len(day_of):,} liquid stock-days; train {int(tr.sum()):,} | selection 2023 {int(va.sum()):,} | out-of-time 2024 {int(te.sum()):,}; embargo gaps {gap1} and {gap2} sessions; labels {time.time() - t0:.0f}s"
    )

    names = list(wf.META)
    x = np.empty((len(day_of), len(names)), dtype="float32")
    col = {n: j for j, n in enumerate(names)}
    for meta, arr in wf.compute_features(op, hi, lo, cl, vo, dq):
        x[:, col[meta.name]] = arr[day_of, iid_of]
    print(f"{len(names)} features computed; {time.time() - t0:.0f}s")
    return Data(
        day_of=day_of,
        iid_of=iid_of,
        dts=dts,
        Y={k: lab[k][day_of, iid_of].astype("int8") for k in ("A", "B10", "C")},
        OUT=lab["outcome"][day_of, iid_of].astype("int8"),
        EXR=lab["exit_return"][day_of, iid_of],
        EARLY=prior5[day_of, iid_of] < 0.03,
        tr=tr,
        va=va,
        te=te,
        names=names,
        col=col,
        X=x,
    )
