import math
from statistics import NormalDist

import pytest

from algo.alpha import stats


def test_ranks_average_the_ties():
    assert stats.ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]
    assert stats.ranks([3]) == [1.0] and stats.ranks([]) == []


def test_spearman_is_one_for_a_monotone_pair_minus_one_for_a_reversed_one_and_hand_computed_with_ties():
    assert stats.spearman([1, 2, 3, 4], [10, 20, 30, 400]) == pytest.approx(
        1.0
    )  # any monotone increase
    assert stats.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # ranks x = [1, 2, 3, 4], ranks y (a tie in the middle) = [1, 2.5, 2.5, 4]: pearson of the ranks
    assert stats.spearman([1, 2, 3, 4], [5, 6, 6, 9]) == pytest.approx(0.9486832980505138)


def test_spearman_is_undefined_below_three_pairs_or_with_no_variation():
    assert stats.spearman([1, 2], [1, 2]) is None
    assert (
        stats.spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None
        and stats.spearman([1, 2, 3], [7, 7, 7]) is None
    )
    with pytest.raises(ValueError, match="same length"):
        stats.spearman([1, 2, 3], [1, 2])


def test_the_cross_sectional_ic_uses_only_names_with_both_a_value_and_a_return_and_needs_a_minimum_of_them():
    feature = {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0, 5: 5.0, 99: 9.0}  # 99 has no return
    fwd = {1: 0.01, 2: 0.02, 3: 0.03, 4: 0.04, 5: 0.05, 98: -1.0}  # 98 has no feature
    assert stats.cross_sectional_ic(feature, fwd, min_names=5) == pytest.approx(1.0)
    assert (
        stats.cross_sectional_ic(feature, fwd, min_names=6) is None
    )  # five names are not enough when six are required


def test_the_ic_summary_of_a_known_series():
    ics = [0.1, 0.3, -0.1, 0.2]
    s = stats.summarise(ics, lag=0)
    assert s.n == 4 and s.mean == pytest.approx(0.125) and s.hit_rate == pytest.approx(0.75)
    sd = math.sqrt(sum((x - 0.125) ** 2 for x in ics) / 3)
    assert s.std == pytest.approx(sd) and s.icir == pytest.approx(0.125 / sd)
    # no autocorrelation correction at lag 0: the long-run variance is the plain population variance of the series
    gamma0 = sum((x - 0.125) ** 2 for x in ics) / 4
    t = 0.125 / math.sqrt(gamma0 / 4)
    assert s.t_stat == pytest.approx(t) and s.p_value == pytest.approx(
        2 * (1 - NormalDist().cdf(abs(t)))
    )


def test_the_newey_west_correction_widens_the_error_for_positively_autocorrelated_series():
    smooth = (
        [0.2] * 4 + [0.0] * 4 + [0.2] * 4 + [0.0] * 4 + [0.2] * 4
    )  # runs of like days: what overlapping horizons produce
    plain, corrected = stats.summarise(smooth, lag=0), stats.summarise(smooth, lag=3)
    assert (
        corrected.mean == plain.mean
        and abs(corrected.t_stat) < abs(plain.t_stat)
        and corrected.p_value > plain.p_value
    )


def test_a_series_that_is_too_short_or_constant_has_no_test():
    assert (
        stats.summarise([], lag=0).t_stat is None and stats.summarise([0.1], lag=0).t_stat is None
    )
    flat = stats.summarise([0.2, 0.2, 0.2, 0.2], lag=1)
    assert (
        flat.mean == pytest.approx(0.2)
        and flat.t_stat is None
        and flat.p_value is None
        and flat.icir is None
    )


def test_holm_adjusts_in_order_never_goes_down_and_caps_at_one():
    adj = stats.holm([0.01, 0.04, 0.03, 0.005])
    # sorted: 0.005*4=0.02, 0.01*3=0.03, 0.03*2=0.06, 0.04*1=0.04 -> running max: 0.02, 0.03, 0.06, 0.06
    assert adj == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert stats.holm([0.6, 0.9]) == [1.0, 1.0] and stats.holm([]) == []
    assert stats.holm([0.2]) == [0.2]


def test_bonferroni_scales_by_the_number_of_tests_ever_run_and_caps_at_one():
    assert stats.bonferroni([0.001, 0.02, 0.5], total_tests=40) == pytest.approx([0.04, 0.8, 1.0])
    with pytest.raises(ValueError, match="at least"):
        stats.bonferroni(
            [0.1, 0.2, 0.3], total_tests=2
        )  # fewer tests than p-values is not possible


# ---- found by mutation testing ---------------------------------------------------------------------------------------
def test_the_newey_west_error_is_worked_by_hand_for_lags_one_and_two():
    ics = [0.2, 0.0, 0.2, 0.0, 0.2]  # mean 0.12; deviations +.08 -.12 +.08 -.12 +.08
    # gamma0 = (3 x .0064 + 2 x .0144) / 5 = .0096; gamma1 = 4 x (-.0096) / 5 = -.00768; gamma2 = (.0064 + .0144 + .0064) / 5 = .00544
    one = stats.summarise(
        ics, lag=1
    )  # long-run variance = .0096 + 2 x (1 - 1/2) x (-.00768) = .00192
    assert one.t_stat == pytest.approx(0.12 / math.sqrt(0.00192 / 5), rel=1e-9)
    two = stats.summarise(
        ics, lag=2
    )  # Bartlett weights for lag 2 are 1 - 1/3 = 2/3 and 1 - 2/3 = 1/3: .0096 + 2 x (2/3) x (-.00768) + 2 x (1/3) x .00544 = .0029866667
    assert two.t_stat == pytest.approx(
        0.12 / math.sqrt((0.0096 - 2 * (2 / 3) * 0.00768 + 2 * (1 / 3) * 0.00544) / 5), rel=1e-9
    )
    assert stats.summarise(ics, lag=0).t_stat == pytest.approx(
        0.12 / math.sqrt(0.0096 / 5), rel=1e-9
    )


def test_a_lag_longer_than_the_series_sums_only_the_autocovariances_that_exist_but_keeps_the_kernel_width():
    short = [
        0.1,
        0.3,
        0.2,
    ]  # mean .2, deviations -.1 .1 0: gamma0 = .02/3, gamma1 = -.01/3, gamma2 = 0
    t = stats.summarise(short, lag=50).t_stat
    lrv = 0.02 / 3 + 2 * (1 - 1 / 51) * (
        -0.01 / 3
    )  # the weights use the kernel width 51, not the 2 lags that exist
    assert t == pytest.approx(0.2 / math.sqrt(lrv / 3), rel=1e-9) and t > 30


def test_one_day_and_two_days_of_ic_report_exactly_what_they_can():
    one = stats.summarise([0.3], lag=0)
    assert one == stats.Summary(1, 0.3, None, None, 1.0, None, None)
    two = stats.summarise([0.1, 0.3], lag=0)
    assert (
        two.n == 2
        and two.mean == pytest.approx(0.2)
        and two.std == pytest.approx(math.sqrt(0.02))
        and two.icir is not None
        and two.hit_rate == 1.0
    )
    assert stats.summarise([0.0, 0.2], lag=0).hit_rate == 0.5  # a zero IC is not a hit


def test_a_constant_series_reports_its_sample_and_spread_and_only_the_test_is_missing():
    flat = stats.summarise([0.2, 0.2, 0.2, 0.2], lag=1)
    assert (
        (flat.n, flat.std, flat.hit_rate) == (4, 0.0, 1.0)
        and flat.icir is None
        and flat.t_stat is None
    )


def test_three_pairs_are_enough_for_a_rank_correlation_and_the_messages_say_what_is_wrong():
    assert stats.spearman([1, 2, 3], [1, 3, 2]) == pytest.approx(0.5)  # exactly three: defined
    with pytest.raises(ValueError) as e:
        stats.spearman([1, 2, 3], [1, 2])
    assert str(e.value) == "spearman needs two series of the same length"
    with pytest.raises(ValueError) as e2:
        stats.bonferroni([0.1, 0.2], total_tests=1)
    assert str(e2.value) == "total_tests must be at least the number of p-values given"
    assert stats.bonferroni([0.1, 0.2], total_tests=2) == [
        0.2,
        0.4,
    ]  # as many tests as p-values is fine


def test_the_last_autocovariance_the_series_has_counts_when_the_lag_reaches_it():
    from fractions import Fraction as F

    ics = [0.1, 0.0, 0.3]  # mean 2/15, deviations -1/30, -2/15, 1/6
    dev = [F(-1, 30), F(-2, 15), F(1, 6)]
    g0 = sum(d * d for d in dev) / 3
    g1 = (dev[1] * dev[0] + dev[2] * dev[1]) / 3
    g2 = (dev[2] * dev[0]) / 3  # the one and only lag-2 term: nonzero here
    lrv = g0 + 2 * F(2, 3) * g1 + 2 * F(1, 3) * g2
    expected = (2 / 15) / math.sqrt(float(lrv) / 3)
    assert stats.summarise(ics, lag=2).t_stat == pytest.approx(expected, rel=1e-9)
    assert stats.summarise(ics, lag=1).t_stat != pytest.approx(
        expected, rel=1e-6
    )  # and it matters: dropping it gives a different answer


def test_benjamini_hochberg_q_values_are_worked_by_hand_and_never_decrease_with_the_p_value():
    q = stats.benjamini_hochberg([0.01, 0.04, 0.03, 0.005])
    # sorted 0.005 (x4/1 = 0.02), 0.01 (x4/2 = 0.02), 0.03 (x4/3 = 0.04), 0.04 (x4/4 = 0.04): already non-decreasing
    assert q == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert stats.benjamini_hochberg([0.9, 0.001]) == pytest.approx([0.9, 0.002])
    assert stats.benjamini_hochberg([0.5, 0.5, 0.5]) == [0.5, 0.5, 0.5]  # ties share one value
    assert stats.benjamini_hochberg([]) == [] and stats.benjamini_hochberg([0.2]) == [0.2]
    one = stats.benjamini_hochberg([0.2, 0.001, 0.3, 0.04, 0.9])
    assert (
        all(a <= 1 for a in one) and one[1] < one[3] < one[0]
    )  # a smaller p never gets a larger q


def test_bh_is_less_strict_than_bonferroni_over_the_same_tests_but_never_below_the_p_value():
    p = [0.001, 0.004, 0.02, 0.2, 0.6, 0.9]
    bh, bon = stats.benjamini_hochberg(p), stats.bonferroni(p, total_tests=len(p))
    assert all(b >= x for b, x in zip(bh, p, strict=True)) and all(
        b <= x + 1e-12 for b, x in zip(bh, bon, strict=True)
    )
