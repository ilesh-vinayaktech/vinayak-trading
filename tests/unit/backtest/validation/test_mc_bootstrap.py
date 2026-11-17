"""Holdout policy v3 section 2: the vectorised stationary bootstrap and the Monte Carlo p-value."""

import math

import numpy as np
import pytest

from algo.backtest.validation import mc_bootstrap as mc
from algo.backtest.validation.evidence import BOOTSTRAP_MEAN_BLOCK
from algo.backtest.validation.stats import annualised_sharpe

RET = [0.01, -0.02, 0.015, 0.003, -0.004, 0.012, 0.0, -0.007]


def test_block_length_matches_the_platform_rule():
    assert mc.RESTART == 1 / BOOTSTRAP_MEAN_BLOCK == 1 / 21


def test_worked_example_by_hand():
    # n = 4; start 2; later steps: u < 1/21 restarts and takes the jump, else previous + 1 modulo 4
    starts = np.array([2], dtype=np.int32)
    u = np.array([[0.5, 0.01, 0.5]])
    jumps = np.array([[3, 1, 3]], dtype=np.int32)
    # 2, then 3 (continue), then restart -> jumps[1] = 1, then 2 (continue)
    assert mc.indices(starts, u, jumps, 4).tolist() == [[2, 3, 1, 2]]
    # wrap from n-1 to 0
    assert mc.indices(np.array([3], dtype=np.int32), np.full((1, 3), 0.9), jumps, 4).tolist() == [
        [3, 0, 1, 2]
    ]
    # a restart uses the jump even when it equals the next index
    assert mc.indices(
        np.array([0], dtype=np.int32), np.array([[0.0, 0.0, 0.0]]), jumps, 4
    ).tolist() == [[0, 3, 1, 3]]


def test_length_continuation_and_restart_rate():
    n = 460
    idx = mc.block_indices(12345, 0, n)
    assert idx.shape == (mc.BLOCK_DRAWS, n) and idx.dtype == np.int32
    step = (idx[:, 1:] - idx[:, :-1]) % n
    cont = step == 1
    rate = 1 - cont.mean()  # restarts that did not land on the next index by chance
    assert abs(rate - mc.RESTART * (1 - 1 / n)) < 0.002
    assert idx.min() == 0 and idx.max() == n - 1
    # initial index uniform over all positions
    counts = np.bincount(idx[:, 0], minlength=n)
    assert (counts > 0).all()
    chi2 = ((counts - mc.BLOCK_DRAWS / n) ** 2 / (mc.BLOCK_DRAWS / n)).sum()
    assert chi2 < n - 1 + 5 * math.sqrt(2 * (n - 1))


def test_same_index_sequence_same_statistic_as_annualised_sharpe():
    n = len(RET)
    idx = mc.block_indices(7, 0, n, d=50)
    r = np.asarray(RET)
    got = mc.sharpe_rows(r[idx])
    for row, g in zip(idx, got, strict=True):
        assert g == pytest.approx(annualised_sharpe([RET[i] for i in row]), rel=1e-9)


def test_statistic_matches_reference_where_defined():
    y = np.array([[0.01, -0.02, 0.03, 0.0], [0.0, 0.0, 0.0, 0.0]])
    s = mc.sharpe_rows(y)
    assert s[0] == pytest.approx(annualised_sharpe([0.01, -0.02, 0.03, 0.0]), rel=1e-12)
    assert math.isinf(s[1]) and s[1] > 0  # zero variance counts as an exceedance


def test_chunking_and_seed_reproducibility():
    ks = {mc.test(RET, seed=99, draws=30_000, rows=m).k for m in (1, 77, 256, 10_000)}
    assert len(ks) == 1
    assert mc.test(RET, seed=99, draws=20_000).k == mc.test(RET, seed=99, draws=20_000).k
    assert mc.block_indices(100, 0, 8).tolist() != mc.block_indices(99, 0, 8).tolist()


def test_stream_is_pinned_by_golden_values():
    assert mc.block_indices(2026, 0, 10)[:3].tolist() == GOLDEN


def test_p_value_rule_and_exact_size_bound():
    assert mc.p_mc(0, 999) == 1 / 1000
    alpha = 0.05 / 30
    b = 1_000_000
    kstar = math.floor(alpha * (b + 1) - 1)
    assert kstar == 1665
    assert mc.rejects(kstar, b, alpha) and not mc.rejects(kstar + 1, b, alpha)
    assert (kstar + 1) / (b + 1) <= alpha  # the exact size of the rule for a uniform ideal p-value
    assert mc.rejects(32, 20_000, alpha) and not mc.rejects(33, 20_000, alpha)


def test_a_strongly_positive_series_is_rejected_and_noise_is_not():
    rng = np.random.default_rng(1)
    good = (0.01 + 0.005 * rng.standard_normal(460)).tolist()
    r = mc.test(good, seed=5, draws=20_000)
    assert mc.rejects(r.k, r.draws, 0.05 / 30)
    noise = (0.01 * rng.standard_normal(460)).tolist()
    assert not mc.rejects(mc.test(noise, seed=5, draws=20_000).k, 20_000, 0.05 / 30)


def test_inputs_are_checked():
    with pytest.raises(ValueError, match="at least 2"):
        mc.test([0.1], seed=1, draws=10_000)
    with pytest.raises(ValueError, match="no variation"):
        mc.test([0.5, 0.5, 0.5], seed=1, draws=10_000)
    with pytest.raises(ValueError, match="multiple"):
        mc.test(RET, seed=1, draws=15_000)
    with pytest.raises(ValueError, match="finite"):
        mc.test([0.1, float("nan"), 0.2], seed=1, draws=10_000)


def test_new_seed_is_128_bit():
    assert 0 <= mc.new_seed() < 2**128
    assert mc.new_seed() != mc.new_seed()


# Pinned from numpy 2.2.6 (PCG64); a change here means the stream changed, which would invalidate every committed seed.
GOLDEN = [
    [6, 7, 8, 9, 1, 2, 3, 4, 5, 6],
    [3, 4, 5, 6, 7, 8, 9, 0, 1, 2],
    [1, 7, 8, 9, 0, 1, 2, 3, 4, 5],
]


def test_result_p_uses_the_monte_carlo_rule():
    assert mc.Result(1.0, 9, 99).p == 10 / 100


def test_a_spawn_key_prefix_gives_an_independent_reproducible_stream():
    a = mc.block_indices(5, 0, 12, d=4, prefix=(1, 2, 1, 7))
    assert a.tolist() == mc.block_indices(5, 0, 12, d=4, prefix=(1, 2, 1, 7)).tolist()
    assert a.tolist() != mc.block_indices(5, 0, 12, d=4, prefix=(1, 2, 1, 8)).tolist()
    assert a.tolist() != mc.block_indices(5, 0, 12, d=4).tolist()


def test_a_series_too_long_for_the_packed_form_is_refused():
    with pytest.raises(ValueError, match="too many sessions"):
        mc.indices(
            np.zeros(1, dtype=np.int32), np.zeros((1, 1)), np.zeros((1, 1), dtype=np.int32), 1 << 15
        )
