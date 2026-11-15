import math
import random

import pytest

from algo.portfolio import allocation as al


def series(seed, vol, n=120, mean=0.0005):
    rng = random.Random(seed)
    return [rng.gauss(mean, vol) for _ in range(n)]


def test_correlation_covariance_and_degenerate_cases():
    a = [1.0, 2.0, 3.0, 4.0]
    assert al.covariance(a, a) == pytest.approx(5 / 3)
    assert al.correlation(a, [2 * x for x in a]) == pytest.approx(1.0)
    assert al.correlation(a, [-x for x in a]) == pytest.approx(-1.0)
    assert al.correlation(a, [5.0] * 4) is None and al.correlation([5.0] * 4, a) is None
    with pytest.raises(al.AllocationError):
        al.covariance([1.0], [1.0])
    with pytest.raises(al.AllocationError):
        al.covariance([1.0, 2.0], [1.0])


def test_equal_risk_weights_are_inverse_volatility_by_hand():
    r = {"A": series(1, 0.01), "B": series(2, 0.02), "C": series(3, 0.04)}
    h = dict.fromkeys(r, "OK")
    out = al.recommend(r, h, method="EQUAL_RISK", limits=al.Limits(max_single=1.0))
    sd = {k: math.sqrt(al.covariance(v, v)) for k, v in r.items()}
    inv = {k: 1 / s for k, s in sd.items()}
    for k in r:
        assert out.weights[k] == pytest.approx(inv[k] / sum(inv.values()))
    assert sum(out.weights.values()) == pytest.approx(1.0) and out.cash == pytest.approx(
        0.0, abs=1e-9
    )


def test_risk_parity_equalises_risk_contributions_even_with_correlated_strategies():
    base = series(1, 0.01)
    r = {
        "A": base,
        "B": [
            x + y for x, y in zip(base, series(2, 0.004), strict=True)
        ],  # highly correlated with A
        "C": series(3, 0.02),
    }
    out = al.recommend(r, dict.fromkeys(r, "OK"), limits=al.Limits(max_single=1.0))
    for share in out.risk_contribution.values():
        assert share == pytest.approx(1 / 3, abs=1e-4)
    assert sum(out.risk_contribution.values()) == pytest.approx(1.0)


def test_the_single_strategy_cap_holds_and_excess_goes_to_the_others_or_to_cash():
    r = {"CALM": series(1, 0.002), "B": series(2, 0.02), "C": series(3, 0.02)}
    out = al.recommend(r, dict.fromkeys(r, "OK"), method="EQUAL_RISK")
    assert out.weights["CALM"] == pytest.approx(0.35) and max(out.weights.values()) <= 0.35 + 1e-9
    assert sum(out.weights.values()) == pytest.approx(
        1.0
    )  # the excess went to B and C (still under the cap)
    two = al.recommend(
        {"A": series(1, 0.01), "B": series(2, 0.01)}, {"A": "OK", "B": "OK"}, method="EQUAL_RISK"
    )
    assert two.weights["A"] == pytest.approx(0.35) and two.cash == pytest.approx(
        0.30
    )  # two strategies cannot fill 100% under a 35% cap
    assert any("cash by the limits" in n for n in two.notes)


def test_cap_weights_directly():
    lim = al.Limits(max_single=0.5, max_total=0.8)
    w = al.cap_weights({"a": 0.9, "b": 0.3, "c": 0.0}, lim)
    assert sum(w.values()) <= 0.8 + 1e-9 and max(w.values()) <= 0.5 + 1e-9
    assert w["c"] == 0.0
    assert al.cap_weights({"a": 0.2, "b": 0.2}, al.Limits()) == {
        "a": 0.2,
        "b": 0.2,
    }  # under the limits: untouched
    assert al.cap_weights({"a": 1.0}, al.Limits(max_single=0.4)) == {
        "a": 0.4
    }  # nobody to pass the excess to


def test_degraded_and_unknown_health_get_nothing_and_say_why():
    r = {"A": series(1, 0.01), "B": series(2, 0.01), "C": series(3, 0.01), "D": series(4, 0.01)}
    h = {"A": "OK", "B": "DEGRADED", "C": "WATCH"}
    out = al.recommend(r, h, method="EQUAL_RISK")
    assert (
        out.weights["B"] == 0.0
        and out.weights["D"] == 0.0
        and out.weights["A"] > 0
        and out.weights["C"] > 0
    )
    assert any("B: DEGRADED" in n for n in out.notes) and any(
        "D: unknown health" in n for n in out.notes
    )
    none = al.recommend(r, {k: "DEGRADED" for k in r})
    assert none.cash == 1.0 and set(none.weights.values()) == {0.0}


def test_volatility_target_only_scales_down():
    r = {"A": series(1, 0.02), "B": series(2, 0.02), "C": series(3, 0.02)}
    h = dict.fromkeys(r, "OK")
    free = al.recommend(r, h, method="EQUAL_RISK")

    def vol(a):
        return math.sqrt(
            sum(a.weights[i] * a.weights[j] * al.covariance(r[i], r[j]) for i in r for j in r)
        )

    target = vol(free) / 2
    cut = al.recommend(r, h, method="EQUAL_RISK", target_vol=target)
    assert (
        vol(cut) == pytest.approx(target)
        and cut.cash > 0.4
        and any("volatility target" in n for n in cut.notes)
    )
    loose = al.recommend(r, h, method="EQUAL_RISK", target_vol=vol(free) * 10)
    assert loose.weights == free.weights  # never levered up


def test_bad_inputs_are_refused():
    r = {"A": series(1, 0.01), "B": series(2, 0.01)}
    h = dict.fromkeys(r, "OK")
    for kwargs in (
        {"method": "MAGIC"},
        {"limits": al.Limits(max_single=0)},
        {"limits": al.Limits(max_total=1.5)},
        {"target_vol": 0},
    ):
        with pytest.raises(al.AllocationError):
            al.recommend(r, h, **kwargs)
    with pytest.raises(al.AllocationError, match="same days"):
        al.recommend({"A": series(1, 0.01, 50), "B": series(2, 0.01, 60)}, h)
    with pytest.raises(al.AllocationError, match="at least 20"):
        al.recommend({"A": series(1, 0.01, 10), "B": series(2, 0.01, 10)}, h)
    with pytest.raises(al.AllocationError, match="no variation"):
        al.recommend({"A": [0.0] * 30, "B": series(2, 0.01, 30)}, h)


def test_risk_parity_refuses_a_portfolio_whose_risk_nets_out_and_one_strategy_is_just_itself():
    base = series(1, 0.01)
    r = {
        "A": base,
        "B": [-x for x in base],
    }  # perfectly hedged: marginal risk of equal weights is zero
    with pytest.raises(al.AllocationError, match="risk adds up"):
        al.recommend(r, {"A": "OK", "B": "OK"}, limits=al.Limits(max_single=1.0))
    solo = al.recommend({"A": base}, {"A": "OK"}, limits=al.Limits(max_single=1.0))
    assert solo.weights == {"A": 1.0} and solo.risk_contribution == {"A": pytest.approx(1.0)}
    assert al.risk_contributions({"A": 0.0}, {"A": {"A": 0.0}}) == {"A": 0.0}


def test_risk_parity_that_does_not_converge_is_an_error_not_a_guess():
    cov = {"A": {"A": 1.0, "B": 0.0}, "B": {"A": 0.0, "B": 4.0}}
    with pytest.raises(al.AllocationError, match="did not converge"):
        al._risk_parity(["A", "B"], cov, iterations=1)
    w = al._risk_parity(["A", "B"], cov)
    assert w["A"] == pytest.approx(2 / 3) and w["B"] == pytest.approx(
        1 / 3
    )  # weights 1/sigma for uncorrelated: 1:0.5


def test_limit_edges_messages_and_covariance_values():
    al.Limits(max_single=1.0, max_total=1.0).validate()
    for bad in (al.Limits(max_single=1.5), al.Limits(max_total=0.0), al.Limits(max_single=0.0)):
        with pytest.raises(al.AllocationError, match=r"limits must be in \(0, 1\]: no leverage"):
            bad.validate()
    assert al.covariance([1.0, 2.0], [3.0, 5.0]) == pytest.approx(
        1.0
    )  # exactly two points is enough
    assert al.covariance([1.0, 2.0, 3.0], [2.0, 4.0, 7.0]) == pytest.approx(2.5)
    with pytest.raises(al.AllocationError, match="at least 2"):
        al.covariance([1.0], [1.0])
    assert al.correlation([1.0, 2.0, 3.0, 4.0], [1.0, 3.0, 2.0, 4.0]) == pytest.approx(0.8)


def test_excess_over_the_cap_is_shared_in_proportion_and_a_total_at_the_limit_is_left_alone():
    w = al.cap_weights({"a": 0.6, "b": 0.2, "c": 0.2}, al.Limits(max_single=0.5))
    assert w == pytest.approx({"a": 0.5, "b": 0.25, "c": 0.25})
    w2 = al.cap_weights({"a": 0.6, "b": 0.3, "c": 0.1}, al.Limits(max_single=0.5))
    assert w2["a"] == 0.5 and w2["b"] == pytest.approx(0.375) and w2["c"] == pytest.approx(0.125)
    assert al.cap_weights({"a": 0.5, "b": 0.5}, al.Limits(max_single=0.5)) == {"a": 0.5, "b": 0.5}


def test_messages_notes_and_health_rules():
    r = {"A": series(1, 0.01, 20), "B": series(2, 0.01, 20)}
    with pytest.raises(al.AllocationError, match="method must be EQUAL_RISK or RISK_PARITY"):
        al.recommend(r, {}, method="X")
    with pytest.raises(al.AllocationError, match="target_vol must be positive"):
        al.recommend(r, {"A": "OK", "B": "OK"}, target_vol=-1)
    with pytest.raises(al.AllocationError, match="same days of returns"):
        al.recommend({"A": [0.1] * 20, "B": [0.1] * 21}, {})
    ok20 = al.recommend(
        r, {"A": "OK", "B": "INSUFFICIENT"}, method="EQUAL_RISK"
    )  # exactly 20 days is enough; INSUFFICIENT is kept
    assert ok20.weights["A"] > 0 and ok20.weights["B"] > 0
    none = al.recommend(r, {"A": "DEGRADED"})
    assert "no strategy is eligible: all cash" in none.notes
    free = al.recommend(
        {k: series(i, 0.02, 120) for i, k in enumerate("ABC", 1)},
        dict.fromkeys("ABC", "OK"),
        method="EQUAL_RISK",
    )
    assert not any("cash" in n for n in free.notes)
