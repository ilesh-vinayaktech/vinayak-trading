"""Holdout policy v3 section 2.2: the calibration design, its randomness and its exact decision rules."""

import json
import math

import numpy as np
import pytest

from algo.backtest.validation import mc_calibration as cal


def sim(series, k=2, sharpe=0.0, root=99, chunk=0):
    rng = np.random.Generator(
        np.random.PCG64(np.random.SeedSequence(entropy=root, spawn_key=(series, chunk, 0)))
    )
    return cal.simulate(series, rng, k, sharpe)


# ---- the exact binomial rules: every figure is the policy's own -----------------------------------------------------------------------------


def test_the_decision_boundaries_and_exact_tails_are_those_in_the_policy():
    n, p = 310_000, 1 / 600
    assert cal.boundary(n, p, 0.05 / 7) == 574 and cal.boundary(n, p, 0.05 / 3) == 567
    assert cal.upper_tail(574, n, p) == pytest.approx(0.006836, abs=1e-6) and cal.upper_tail(
        573, n, p
    ) == pytest.approx(0.007691, abs=1e-6)
    assert cal.upper_tail(567, n, p) == pytest.approx(0.015097, abs=1e-6) and cal.upper_tail(
        566, n, p
    ) == pytest.approx(0.016800, abs=1e-6)
    assert cal.boundary(300_000, p, 0.05 / 7) == 557 and cal.boundary(230_000, p, 0.05 / 7) == 433


def test_intervals():
    lo, hi = cal.clopper_pearson(5, 100)
    assert (lo, hi) == (pytest.approx(0.0164, abs=1e-4), pytest.approx(0.1128, abs=1e-4))
    assert cal.clopper_pearson(0, 100)[0] == 0.0 and cal.clopper_pearson(100, 100)[1] == 1.0
    w = cal.wilson(50, 100)
    assert w[0] < 0.5 < w[1]


# ---- the series ------------------------------------------------------------------------------------------------------------------------------


def test_the_stream_is_pinned_by_golden_values():
    r, ri = sim(0)
    assert r[0, :3].tolist() == pytest.approx([0.01721433, -0.0011105738, -0.0007200744], abs=1e-9)
    assert ri[1, :2].tolist() == pytest.approx([0.0058724272, -0.0104106813], abs=1e-9)
    assert sim(3)[0][0, :3].tolist() == pytest.approx(
        [0.0044462041, 0.0001745885, 0.0238957702], abs=1e-9
    )
    assert sim(5)[0][0, :3].tolist() == pytest.approx(
        [-0.0089053934, 0.0045764258, 0.0018893106], abs=1e-9
    )
    assert sim(6)[0][0, :3].tolist() == pytest.approx(
        [-0.0122365953, -0.0027963438, 0.01487238], abs=1e-9
    )


def test_every_series_has_460_sessions_unit_variance_and_the_stated_sharpe():
    for series in range(len(cal.SERIES)):
        r, _ = sim(series, k=400, sharpe=1.0)
        assert r.shape == (400, 460)
        x = (r - 1.0 * cal.S_STRAT / math.sqrt(252)) / cal.S_STRAT
        assert abs(x.var() - 1) < 0.1, cal.SERIES[series]
        assert abs(r.mean() / r.std() * math.sqrt(252) - 1.0) < 0.35, cal.SERIES[series]


def test_the_skew_normal_series_is_negatively_skewed_minus_0_80():
    r, _ = sim(4, k=400)
    x = ((r - r.mean()) / r.std()).ravel()
    assert (x**3).mean() == pytest.approx(-0.80, abs=0.06)


def test_the_student_t_series_has_heavy_tails():
    x = sim(3, k=400)[0].ravel()
    z = (x - x.mean()) / x.std()
    assert (z**4).mean() > 4.5  # kurtosis of a t with 4 d.f. is infinite; a normal's is 3


def test_the_index_is_correlated_through_the_underlying_normals():
    r, ri = sim(0, k=200)
    assert np.mean([np.corrcoef(a, b)[0, 1] for a, b in zip(r, ri, strict=True)]) == pytest.approx(
        0.7, abs=0.02
    )
    assert ri.mean() / ri.std() * math.sqrt(252) == pytest.approx(
        0.5, abs=0.4
    )  # the index's true Sharpe is 0.5


def test_the_drift_diagnostic_has_the_stated_unconditional_sharpe_and_a_worse_volatile_state():
    for target in (0.0, -0.5, -1.0):
        r, _ = sim(cal.DRIFT_SERIES, k=400, sharpe=target)
        assert r.mean() / r.std() * math.sqrt(252) == pytest.approx(target, abs=0.3)


def test_an_unknown_series_is_refused():
    with pytest.raises(ValueError, match="no series"):
        sim(99)


# ---- chunks, resumption and the report -------------------------------------------------------------------------------------------------------


def test_a_chunk_depends_only_on_its_keys_and_counts_are_consistent():
    a = cal.run_chunk(7, 0, 3, 0.0, datasets=20, draws=10_000)
    assert a == cal.run_chunk(7, 0, 3, 0.0, datasets=20, draws=10_000)
    assert a != cal.run_chunk(7, 0, 4, 0.0, datasets=20, draws=10_000)
    assert a["rej_c"] <= a["rej_1"] <= a["rej_5"] <= a["datasets"] and a["full_pass"] <= a["rej_c"]


def test_strong_returns_pass_the_whole_policy_and_noise_does_not():
    strong = cal.run_chunk(7, 0, 0, 2.0, datasets=30, draws=10_000)
    assert strong["rej_5"] > 0 and strong["floors"] > 0
    assert cal.run_chunk(7, 0, 0, 0.0, datasets=30, draws=10_000)["rej_c"] == 0


def test_a_stopped_run_resumes_at_the_unfinished_chunk_and_gives_the_same_answer(tmp_path):
    cal.run(5, tmp_path, [0], chunks=3, datasets=10, draws=10_000, workers=2)
    done = {f.name: f.read_text() for f in tmp_path.glob("*.json")}
    assert len(done) == 3
    (tmp_path / "s0_sr0.0_c1.json").unlink()
    ticks = []
    cal.run(
        5,
        tmp_path,
        [0],
        chunks=3,
        datasets=10,
        draws=10_000,
        workers=2,
        progress=lambda i, n: ticks.append((i, n)),
    )
    assert {f.name: f.read_text() for f in tmp_path.glob("*.json")} == done and ticks[-1] == (3, 3)
    assert cal.totals(tmp_path, 0)["datasets"] == 30


def fake(out, series, sharpe, rej, datasets=310_000):
    (out / f"s{series}_sr{sharpe}_c0.json").write_text(
        json.dumps(
            {
                "datasets": datasets,
                "rej_5": 0,
                "rej_1": 0,
                "rej_c": rej,
                "floors": 0,
                "full_pass": 0,
                "corr_mean": 0.7,
            }
        )
    )


def test_calibration_fails_at_574_on_any_decision_series_and_at_567_on_any_drift_series(tmp_path):
    for i in range(7):
        fake(tmp_path, i, 0.0, 517)
    for sr in (0.0, -0.5, -1.0):
        fake(tmp_path, cal.DRIFT_SERIES, sr, 517)
    rep = cal.report(tmp_path)
    assert rep["complete"] and not rep["calibration_failed"]
    fake(tmp_path, 3, 0.0, 573)
    assert not cal.report(tmp_path)["calibration_failed"]
    fake(tmp_path, 3, 0.0, 574)
    assert cal.report(tmp_path)["calibration_failed"]
    fake(tmp_path, 3, 0.0, 517)
    fake(tmp_path, cal.DRIFT_SERIES, -0.5, 566)
    assert not cal.report(tmp_path)["calibration_failed"]
    fake(tmp_path, cal.DRIFT_SERIES, -0.5, 567)
    assert cal.report(tmp_path)["calibration_failed"]


def test_an_incomplete_run_is_reported_as_incomplete_never_as_passed(tmp_path):
    fake(tmp_path, 0, 0.0, 10, datasets=1000)
    rep = cal.report(tmp_path)
    assert rep["complete"] is False and rep["decision"][0]["fail"] is False


def test_the_pool_task_runs_a_chunk_once_and_a_second_call_finds_it_done(tmp_path):
    args = (5, 0, 0, 0.0, 10, 10_000, str(tmp_path))
    path = cal._task(args)
    first = json.loads(open(path).read())
    assert first["datasets"] == 10 and first["root"] == f"{5:032x}"
    assert (
        cal._task(args) == path and json.loads(open(path).read()) == first
    )  # resumed: not run again


def test_the_boundary_search_also_walks_down_when_the_start_is_already_inside_the_tail():
    n, p, alpha = 10_000, 1 / 600, 0.99
    best = next(c for c in range(0, n) if cal.upper_tail(c, n, p) <= alpha)
    assert cal.boundary(n, p, alpha) == best
