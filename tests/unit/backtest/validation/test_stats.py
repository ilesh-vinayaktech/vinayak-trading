import math
import random

import pytest

from algo.backtest.validation.stats import (
    annualised_sharpe,
    bootstrap_interval,
    deflated_sharpe,
    expected_max_sharpe,
    kurtosis,
    max_drawdown,
    mean,
    pbo_cscv,
    psr,
    sharpe_per_period,
    skew,
    stationary_bootstrap,
    stdev,
)


# ---- moments --------------------------------------------------------------------------------
def test_mean_and_sample_stdev_hand_computed():
    assert mean([2, 4, 6]) == 4 and stdev([2, 4, 6]) == pytest.approx(2.0)
    assert stdev([0.02, 0.0, 0.02, 0.0]) == pytest.approx(math.sqrt(4 * 0.01**2 / 3))


def test_sharpe_hand_computed_and_undefined_cases():
    r = [0.02, 0.0, 0.02, 0.0]  # mean 0.01, sd 0.011547
    assert sharpe_per_period(r) == pytest.approx(0.01 / math.sqrt(4 * 0.01**2 / 3))
    assert annualised_sharpe(r) == pytest.approx(sharpe_per_period(r) * math.sqrt(252))
    assert annualised_sharpe(r, periods=12) == pytest.approx(sharpe_per_period(r) * math.sqrt(12))
    assert sharpe_per_period([0.01]) is None and sharpe_per_period([]) is None
    assert sharpe_per_period([0.01, 0.01, 0.01]) is None  # no variation => undefined, not infinite
    assert annualised_sharpe([0.01, 0.01]) is None


def test_skew_and_kurtosis_hand_computed():
    assert skew([1, 2, 3, 4, 5]) == pytest.approx(0.0)
    assert kurtosis([1, 2, 3, 4, 5]) == pytest.approx(6.8 / 4)  # m4 = 6.8, m2 = 2
    assert kurtosis([-1, 1, -1, 1]) == pytest.approx(1.0)
    assert skew([1, 1, 1, 10]) > 0 > skew([-10, 1, 1, 1])


# ---- PSR / expected max / DSR ----------------------------------------------------------------
def test_psr_matches_independent_values():
    assert psr(0.1, 0.0, 100, 0.0, 3.0) == pytest.approx(0.839525, abs=1e-5)
    assert psr(0.1, 0.0, 100, -0.5, 5.0) == pytest.approx(0.833082, abs=1e-5)  # fat left tail hurts
    assert psr(0.1, 0.1, 100, 0.0, 3.0) == pytest.approx(0.5)


def test_psr_increases_with_sample_size_and_sharpe_and_falls_with_the_benchmark():
    base = psr(0.1, 0.0, 100, 0, 3)
    assert psr(0.1, 0.0, 400, 0, 3) > base and psr(0.2, 0.0, 100, 0, 3) > base
    assert psr(0.1, 0.05, 100, 0, 3) < base


def test_psr_refuses_nonsense():
    with pytest.raises(ValueError, match="^need at least 2 observations$"):
        psr(0.1, 0, 1, 0, 3)
    with pytest.raises(ValueError, match="variance is not positive"):
        psr(10.0, 0, 100, 5.0, 1.0)  # 1 - 50 + 0 < 0


def test_expected_max_sharpe_matches_independent_values():
    assert expected_max_sharpe(100, 0.01) == pytest.approx(0.253060, abs=1e-5)
    assert expected_max_sharpe(10, 0.0025) == pytest.approx(0.078730, abs=1e-5)
    assert expected_max_sharpe(1000, 0.04) == pytest.approx(0.651024, abs=1e-5)


def test_expected_max_sharpe_grows_with_trials_and_dispersion_and_is_zero_for_one_trial():
    assert expected_max_sharpe(1, 0.04) == 0.0
    assert expected_max_sharpe(50, 0.01) > expected_max_sharpe(5, 0.01)
    assert expected_max_sharpe(50, 0.04) > expected_max_sharpe(50, 0.01)
    assert expected_max_sharpe(50, 0.0) == 0.0


def test_expected_max_sharpe_refuses_nonsense():
    with pytest.raises(ValueError, match="^n_trials must be at least 1$"):
        expected_max_sharpe(0, 0.01)
    with pytest.raises(ValueError, match="^variance cannot be negative$"):
        expected_max_sharpe(5, -0.01)


def noisy(n, mu, sd, seed):
    rng = random.Random(seed)
    return [rng.gauss(mu, sd) for _ in range(n)]


def test_deflated_sharpe_falls_as_the_number_of_trials_grows():
    r = noisy(750, 0.0012, 0.01, 7)
    one = deflated_sharpe(r, 1, 0.0004)
    many = deflated_sharpe(r, 100, 0.0004)
    assert one is not None and many is not None
    assert one == pytest.approx(
        psr(sharpe_per_period(r), 0.0, 750, skew(r), kurtosis(r))
    )  # N=1: PSR vs 0
    assert many < one


def test_a_strong_result_survives_deflation_and_a_weak_one_does_not():
    strong = noisy(1000, 0.003, 0.01, 1)
    weak = noisy(1000, 0.0003, 0.01, 2)
    assert deflated_sharpe(strong, 20, 0.0002) > 0.95
    assert deflated_sharpe(weak, 20, 0.0002) < 0.5


def test_deflated_sharpe_is_undefined_for_flat_or_tiny_series():
    assert deflated_sharpe([0.01] * 10, 5, 0.01) is None
    assert deflated_sharpe([0.01, 0.02, 0.0], 5, 0.01) is None  # fewer than 4 observations


# ---- drawdown --------------------------------------------------------------------------------
def test_max_drawdown_hand_computed():
    assert max_drawdown([0.1, -0.2, 0.05]) == pytest.approx(0.88 / 1.1 - 1)  # -0.2
    assert max_drawdown([0.1, 0.1, 0.1]) == 0.0
    assert max_drawdown([]) == 0.0
    assert max_drawdown([-0.1, 0.5, -0.3]) == pytest.approx(0.99 * 1.5 * 0.7 / (0.99 * 1.5) - 1)


# ---- bootstrap -------------------------------------------------------------------------------
def test_the_bootstrap_is_deterministic_for_a_seed_and_differs_across_seeds():
    r = noisy(60, 0.001, 0.01, 3)
    a = stationary_bootstrap(r, 5, 4, seed=11)
    assert a == stationary_bootstrap(r, 5, 4, seed=11) and a != stationary_bootstrap(
        r, 5, 4, seed=12
    )
    assert len(a) == 5 and all(len(s) == 60 for s in a)
    assert all(x in r for s in a for x in s)  # only original observations


def test_blocks_keep_serial_order_when_blocks_are_long():
    r = list(range(100))
    s = stationary_bootstrap(r, 1, mean_block=1e9, seed=1)[0]  # one giant block: consecutive values
    assert all((b - a) % 100 == 1 for a, b in zip(s, s[1:], strict=False))
    shuffled = stationary_bootstrap(r, 1, mean_block=1, seed=1)[0]  # blocks of ~1: nearly iid
    assert any((b - a) % 100 != 1 for a, b in zip(shuffled, shuffled[1:], strict=False))


def test_bootstrap_refuses_nonsense():
    with pytest.raises(ValueError, match="^nothing to resample$"):
        stationary_bootstrap([], 1, 5, 0)
    with pytest.raises(ValueError, match="^mean_block must be at least 1$"):
        stationary_bootstrap([0.1], 1, 0.5, 0)


def test_the_interval_brackets_the_point_estimate_and_widens_with_noise():
    calm, wild = noisy(250, 0.001, 0.005, 5), noisy(250, 0.001, 0.02, 5)
    ci_calm = bootstrap_interval(calm, annualised_sharpe, seed=1)
    ci_wild = bootstrap_interval(wild, annualised_sharpe, seed=1)
    assert ci_calm.low <= ci_calm.point <= ci_calm.high
    assert ci_calm.point == annualised_sharpe(calm)
    assert bootstrap_interval(calm, annualised_sharpe, seed=1) == ci_calm  # reproducible
    dd = bootstrap_interval(wild, max_drawdown, seed=1)
    assert dd.low <= dd.point <= dd.high <= 0 and ci_wild.high - ci_wild.low > 0


def test_the_interval_is_none_when_the_statistic_is_undefined():
    assert bootstrap_interval([0.01, 0.01, 0.01], annualised_sharpe) is None
    assert bootstrap_interval([0.01, 0.02], lambda s: None) is None
    calls = iter([1.0])  # defined for the point estimate, undefined for every resample
    assert bootstrap_interval([0.01, 0.02], lambda s: next(calls, None), n_boot=5) is None


def test_confidence_level_controls_the_width():
    r = noisy(250, 0.001, 0.01, 8)
    narrow = bootstrap_interval(r, annualised_sharpe, confidence=0.5, seed=2)
    wide = bootstrap_interval(r, annualised_sharpe, confidence=0.99, seed=2)
    assert wide.high - wide.low > narrow.high - narrow.low


# ---- PBO -------------------------------------------------------------------------------------
def test_a_consistently_best_strategy_has_zero_probability_of_overfitting():
    rng = random.Random(0)
    base = [rng.gauss(0, 0.01) for _ in range(160)]
    strategies = [[b + 0.002 * k for b in base] for k in range(5)]  # k=4 is always best
    r = pbo_cscv(strategies, n_blocks=8)
    assert r.pbo == 0.0 and r.splits == 70 and all(lg > 0 for lg in r.logits)


def test_pure_noise_strategies_have_a_pbo_near_one_half():
    rng = random.Random(42)
    strategies = [[rng.gauss(0, 0.01) for _ in range(240)] for _ in range(12)]
    assert 0.3 < pbo_cscv(strategies, n_blocks=8).pbo < 0.7


def test_picking_the_in_sample_winner_of_anti_correlated_strategies_overfits():
    # A is good in the first half of every block-pair, B the reverse: whoever wins in-sample loses OOS
    a = ([0.02, 0.0] * 2 + [-0.02, 0.0] * 2) * 8
    b = [-x for x in a]
    r = pbo_cscv([a, b], n_blocks=4)
    assert r.pbo >= 0.5


@pytest.mark.parametrize(
    ("matrix", "blocks", "msg"),
    [
        ([[0.1] * 16], 8, "at least 2 strategies"),
        ([[0.1] * 16, [0.2] * 16], 7, "even number"),
        ([[0.1] * 16, [0.2] * 16], 0, "even number"),
        ([[0.1] * 16, [0.2] * 15], 8, "same length"),
        ([[0.1] * 4, [0.2] * 4], 8, "fewer observations than blocks"),
    ],
)
def test_pbo_refuses_nonsense(matrix, blocks, msg):
    with pytest.raises(ValueError, match=msg):
        pbo_cscv(matrix, blocks)


def test_the_mean_pairwise_correlation_is_one_for_scaled_copies_and_low_for_unrelated_series():
    from algo.backtest.validation.stats import mean_pairwise_correlation

    base = [0.01, -0.02, 0.015, 0.0, 0.03, -0.01, 0.02, -0.005]
    assert mean_pairwise_correlation(
        [base, [2 * x for x in base], [x + 0.001 for x in base]]
    ) == pytest.approx(1.0)
    other = [0.02, 0.01, -0.03, 0.015, -0.01, 0.0, 0.01, -0.02]
    assert abs(mean_pairwise_correlation([base, other]) or 1) < 0.5
    assert (
        mean_pairwise_correlation([base]) is None
        and mean_pairwise_correlation([base, [0.0] * 8]) is None
    )
