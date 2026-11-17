"""Holdout policy v3 section 2: the acceptance decision of a holdout batch candidate."""

import math

import numpy as np

from algo.backtest.validation.gates import Thresholds
from algo.research import holdout_batch
from algo.research.verdict import HOLDOUT_ALPHA, holdout_gates_v3

TH = Thresholds(
    0.8, 0.95, 0.2, 1.25, 1.0, 0.3, 0.5, 0.2, 252, 2, 0.5, 0.02
)  # thresholds v3: no absolute drawdown cap
DRAWS = 20_000


def series(drift, n=460, noise=0.004, seed=1):
    return (drift + noise * np.random.default_rng(seed).standard_normal(n)).tolist()


def gate(gates, name):
    return next(g for g in gates if g["name"] == name)


def run(r, b, **kw):
    return holdout_gates_v3(r, b, TH, seed=7, draws=DRAWS, **kw)


def test_alpha_is_the_fixed_family_budget():
    assert HOLDOUT_ALPHA == 0.05 / holdout_batch.BUDGET


def test_a_strong_series_that_beats_the_index_passes_every_gate():
    gates, ev = run(series(0.003), series(0.0004, seed=2))
    assert {g["name"]: g["status"] for g in gates} == dict.fromkeys(
        ("holdout_significance", "holdout_sharpe", "holdout_drawdown", "holdout_beats_benchmark"),
        "PASS",
    )
    assert (
        ev["draws"] == DRAWS and ev["seed"] == f"{7:032x}" and ev["k"] <= 32 and ev["days"] == 460
    )


def test_a_good_looking_but_not_significant_series_fails_only_the_primary_test():
    # about 1.2 Sharpe over 460 days: clears the floors, far from 0.05/30
    r = series(0.0008, noise=0.01, seed=3)
    gates, ev = run(r, series(0.0002, noise=0.01, seed=4))
    assert gate(gates, "holdout_significance")["status"] == "FAIL"
    assert ev["sharpe"] > 0.8 and gate(gates, "holdout_sharpe")["status"] == "PASS"


def test_the_floors_can_only_remove_passes():
    gates, _ = run(series(0.0001), series(0.0004, seed=2))
    assert gate(gates, "holdout_sharpe")["status"] == "FAIL"
    gates, _ = run(series(0.003), series(0.003))  # the index did exactly as well: no edge
    assert gate(gates, "holdout_beats_benchmark")["status"] == "FAIL"


def test_drawdown_is_judged_against_the_index_on_the_same_dates_at_1_25x():
    bench = [0.0] * 100 + [-0.10] + [0.001] * 359  # index drawdown 10%
    base = [0.001] * 460
    ok = base[:200] + [-0.125] + base[201:]  # exactly 1.25x: the index limit is inclusive
    assert gate(run(ok, bench)[0], "holdout_drawdown")["status"] == "PASS"
    worse = base[:200] + [-0.13] + base[201:]
    g = gate(run(worse, bench)[0], "holdout_drawdown")
    assert g["status"] == "FAIL" and "1.25" in g["detail"]


def test_no_reliable_index_is_insufficient_evidence_never_a_pass():
    r = series(0.003)
    for bench in (
        None,
        series(0.0004)[:-1],
        [0.001] * 460,
    ):  # missing, misaligned, no drawdown at all
        assert gate(run(r, bench)[0], "holdout_drawdown")["status"] == "INSUFFICIENT_EVIDENCE"
    for bench in (None, series(0.0004)[:-1]):  # no sessions to compare on
        assert (
            gate(run(r, bench)[0], "holdout_beats_benchmark")["status"] == "INSUFFICIENT_EVIDENCE"
        )


def test_missing_or_flat_returns_are_insufficient_evidence_on_the_primary_test():
    for r in ([0.001], [0.5] * 460, [0.01, math.nan, 0.02]):
        gates, _ = run(r, series(0.0004, n=len(r)))
        assert gate(gates, "holdout_significance")["status"] == "INSUFFICIENT_EVIDENCE"
        assert gate(gates, "holdout_significance")["passed"] is False


def test_the_same_seed_gives_the_same_decision():
    r, b = series(0.003), series(0.0004, seed=2)
    assert run(r, b)[1]["k"] == run(r, b)[1]["k"]
