import random
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from algo.alpha import discover


def sessions(n, start=date(2024, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def flat_then(closes_by_iid, days):
    return {i: dict(zip(days, cs, strict=True)) for i, cs in closes_by_iid.items()}


def test_the_forward_return_starts_the_session_after_the_signal_and_ends_h_sessions_later():
    days = sessions(8)
    closes = flat_then({1: [100, 110, 121, 133.1, 146.41, 161.051, 177.1561, 194.87171]}, days)
    r = discover.forward_returns(closes, days, horizon=2, last_allowed=days[-1])
    # signal on day 0 -> bought at day 1's close (110), sold at day 3's close (133.1): +21%
    assert r[days[0]][1] == pytest.approx(133.1 / 110 - 1)
    assert r[days[1]][1] == pytest.approx(146.41 / 121 - 1)
    assert (
        days[-1] not in r and days[-2] not in r and days[-3] not in r
    )  # no later session to end on


def test_an_observation_whose_return_would_reach_past_the_last_allowed_day_is_dropped_so_the_holdout_is_never_touched():
    days = sessions(10)
    closes = flat_then({1: [100 + i for i in range(10)]}, days)
    r = discover.forward_returns(closes, days, horizon=2, last_allowed=days[5])
    assert max(r) == days[2]  # signal day 2 -> buy day 3 -> sell day 5, the last allowed session
    assert all(d <= days[2] for d in r)


def test_a_missing_close_at_either_end_means_no_return_for_that_stock_that_day_and_nothing_is_filled_in():
    days = sessions(6)
    closes = flat_then({1: [100, 101, 102, 103, 104, 105], 2: [50, 51, 52, 53, 54, 55]}, days)
    del closes[2][days[1]]  # stock 2 has no bar on the buy day of signal day 0
    r = discover.forward_returns(closes, days, horizon=2, last_allowed=days[-1])
    assert set(r[days[0]]) == {1} and set(r[days[1]]) == {1, 2}


def make_market(n_days=260, n_stocks=40, seed=1, signal=0.0):
    """Daily returns are noise; the return from the close of day t+1 to the close of day t+2 also carries `signal` x 1% x the feature of day t,
    so the feature is informative about exactly the window a forward return that starts the session after the signal measures."""
    rng = random.Random(seed)
    days = sessions(n_days)
    feature = {
        (i, d): D(str(round(rng.gauss(0, 1), 6))) for i in range(1, n_stocks + 1) for d in days
    }
    closes: dict[int, dict] = {}
    for i in range(1, n_stocks + 1):
        price, series = 100.0, {}
        for t, d in enumerate(days):
            if t >= 2:
                price *= 1 + rng.gauss(0, 0.01) + signal * 0.01 * float(feature[(i, days[t - 2])])
            elif t == 1:
                price *= 1 + rng.gauss(0, 0.01)
            series[d] = D(str(round(price, 6)))
        closes[i] = series
    return days, feature, closes


def test_a_planted_signal_is_found_with_the_right_sign_and_noise_is_not():
    days, feature, closes = make_market(signal=1.0)
    ev = discover.evaluate(
        "planted", "1", feature, closes, days, horizon=1, last_allowed=days[-1], min_names=20
    )
    assert ev.mean_ic > 0.2 and ev.p_value < 1e-6 and ev.days > 200 and ev.avg_names == 40
    days, feature, closes = make_market(seed=7, signal=0.0)
    noise = discover.evaluate(
        "noise", "1", feature, closes, days, horizon=1, last_allowed=days[-1], min_names=20
    )
    assert abs(noise.mean_ic) < 0.05 and noise.p_value > 0.01


def test_evaluate_reports_the_sample_and_is_reproducible_to_the_bit():
    days, feature, closes = make_market(n_days=120, signal=0.5)
    a = discover.evaluate(
        "f", "1", feature, closes, days, horizon=5, last_allowed=days[-1], min_names=20
    )
    b = discover.evaluate(
        "f", "1", feature, closes, days, horizon=5, last_allowed=days[-1], min_names=20
    )
    assert (
        a == b
        and a.horizon == 5
        and (a.feature, a.version) == ("f", "1")
        and a.sha256 == b.sha256
        and len(a.sha256) == 64
    )


def test_changing_prices_after_the_last_allowed_day_cannot_change_any_result():
    days, feature, closes = make_market(n_days=150, signal=0.5)
    cut = days[100]
    base = discover.evaluate(
        "f", "1", feature, closes, days, horizon=5, last_allowed=cut, min_names=20
    )
    tampered = {
        i: {d: (c * 3 if d > cut else c) for d, c in series.items()} for i, series in closes.items()
    }
    again = discover.evaluate(
        "f", "1", feature, tampered, days, horizon=5, last_allowed=cut, min_names=20
    )
    assert base == again


def test_days_with_too_few_names_are_skipped_and_an_empty_result_has_no_test():
    days = sessions(30)
    closes = flat_then({1: [100 + i for i in range(30)], 2: [200 + i for i in range(30)]}, days)
    feature = {(i, d): D(i) for i in (1, 2) for d in days}
    ev = discover.evaluate(
        "f", "1", feature, closes, days, horizon=2, last_allowed=days[-1], min_names=5
    )
    assert ev.days == 0 and ev.mean_ic is None and ev.p_value is None and ev.avg_names == 0


def test_discover_tests_every_feature_at_every_horizon_in_a_stable_order():
    days, feature, closes = make_market(n_days=80, signal=0.5)
    out = discover.discover(
        {("b", "1"): feature, ("a", "1"): feature},
        closes,
        days,
        horizons=(5, 1),
        last_allowed=days[-1],
        min_names=20,
    )
    assert [(e.feature, e.horizon) for e in out] == [("a", 1), ("a", 5), ("b", 1), ("b", 5)]


def test_the_ic_lag_for_overlapping_horizons_is_horizon_minus_one():
    assert discover.overlap_lag(1) == 0 and discover.overlap_lag(20) == 19


# ---- found by mutation testing ---------------------------------------------------------------------------------------
def test_a_zero_close_gives_no_return_and_a_close_of_exactly_one_is_a_price_like_any_other():
    days = sessions(6)
    closes = flat_then({1: [100, 0, 102, 103, 104, 105], 2: [1, 1, 2, 2, 3, 3]}, days)
    r = discover.forward_returns(closes, days, horizon=1, last_allowed=days[-1])
    assert 1 not in r[days[0]]  # the buy-day close is zero: no return, and no division by zero
    assert r[days[0]][2] == pytest.approx(1.0) and r[days[1]][2] == pytest.approx(
        0.0
    )  # a price of exactly 1 (1 -> 2, then 2 -> 2) is fine


def test_days_without_a_feature_at_the_start_do_not_stop_the_days_after_them():
    days, feature, closes = make_market(n_days=120, signal=1.0)
    late = {
        k: v for k, v in feature.items() if k[1] >= days[30]
    }  # a feature with a warm-up: nothing for the first 30 sessions
    ev = discover.evaluate(
        "late", "1", late, closes, days, horizon=1, last_allowed=days[-1], min_names=20
    )
    assert ev.days > 80 and ev.mean_ic is not None and ev.mean_ic > 0.2


def test_the_evidence_carries_every_statistic_the_summary_computed_and_the_version_it_was_given():
    days, feature, closes = make_market(n_days=150, signal=0.5)
    ev = discover.evaluate(
        "f", "7", feature, closes, days, horizon=3, last_allowed=days[-1], min_names=20
    )
    assert ev.version == "7" and ev.std_ic and ev.icir == pytest.approx(ev.mean_ic / ev.std_ic)
    assert 0 < ev.hit_rate < 1 and ev.t_stat is not None and ev.p_value is not None
    out = discover.discover(
        {("f", "7"): feature}, closes, days, horizons=(3,), last_allowed=days[-1], min_names=20
    )
    assert out == [ev] and out[0].version == "7"


def test_a_long_run_reports_before_each_test_in_the_stable_order():
    from datetime import date, timedelta
    from decimal import Decimal as D

    from algo.alpha import discover

    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(30)]
    closes = {i: {d: D(100 + i + n) for n, d in enumerate(days)} for i in range(5)}
    feats = {
        ("b_feat", "1"): {(i, d): D(i) for i in range(5) for d in days},
        ("a_feat", "1"): {(i, d): D(n) for i in range(5) for n, d in enumerate(days)},
    }
    seen = []
    out = discover.discover(
        feats,
        closes,
        days,
        horizons=(5, 1),
        last_allowed=days[-1],
        min_names=3,
        heartbeat=lambda *a: seen.append(a),
    )
    assert seen == [
        ("a_feat", 1, 1, 4),
        ("a_feat", 5, 2, 4),
        ("b_feat", 1, 3, 4),
        ("b_feat", 5, 4, 4),
    ]  # feature name, then horizon; "k of n"
    assert [(e.feature, e.horizon) for e in out] == [
        ("a_feat", 1),
        ("a_feat", 5),
        ("b_feat", 1),
        ("b_feat", 5),
    ]
    assert (
        discover.discover(feats, closes, days, horizons=(5, 1), last_allowed=days[-1], min_names=3)
        == out
    )  # reporting changes nothing


def test_testing_the_features_one_at_a_time_gives_exactly_the_evidence_of_testing_them_all_together():
    from datetime import date, timedelta
    from decimal import Decimal as D

    from algo.alpha import discover

    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(40)]
    closes = {
        i: {d: D(100 + (i * 7 + n * 3) % 11 + n) for n, d in enumerate(days)} for i in range(6)
    }
    feats = {
        ("zeta", "1"): {(i, d): D((i * 5 + n) % 9) for i in range(6) for n, d in enumerate(days)},
        ("alpha", "1"): {
            (i, d): D((i * 3 + n * 2) % 7) for i in range(6) for n, d in enumerate(days)
        },
        ("mid", "2"): {(i, d): D(i) for i in range(6) for d in days},
    }
    kw = dict(horizons=(5, 1), last_allowed=days[-1], min_names=4)
    together = discover.discover(feats, closes, days, **kw)
    apart = [
        e for key in sorted(feats) for e in discover.discover({key: feats[key]}, closes, days, **kw)
    ]
    assert apart == together and [e.feature for e in together][:2] == ["alpha", "alpha"]
