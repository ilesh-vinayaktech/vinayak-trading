import math
import random

import pytest

from algo.learning import degradation as dg


def noise(seed, mean, n, vol=0.01):
    rng = random.Random(seed)
    return [rng.gauss(mean, vol) for _ in range(n)]


REF = noise(1, 0.0008, 750)  # three years of development returns


def test_returns_that_look_like_the_reference_are_ok():
    h = dg.assess(REF, noise(4, 0.0008, 60))
    assert h.status == "OK" and h.reasons == [] and h.evidence["live_days"] == 60


def test_a_clear_fall_in_the_mean_return_is_degraded_and_a_mild_one_is_a_watch():
    bad = dg.assess(REF, noise(3, -0.004, 60))
    assert bad.status == "DEGRADED" and any("mean return" in r for r in bad.reasons)
    mild = dg.assess(
        REF,
        noise(4, 0.0008 - 0.0030, 60, vol=0.01),
        thresholds=dg.Thresholds(watch_z=-1.0, degraded_z=-4.0),
    )
    assert mild.status == "WATCH"


def test_the_z_score_is_the_gap_in_means_over_the_standard_error_worked_by_hand():
    ref = [0.01, -0.01] * 100  # mean 0, sample std close to 0.01
    live = [-0.005] * 25
    h = dg.assess(ref, live, thresholds=dg.Thresholds(min_days=20))
    ref_std = math.sqrt(sum(x * x for x in ref) / (len(ref) - 1))
    assert h.evidence["z"] == pytest.approx((-0.005 - 0.0) / (ref_std / math.sqrt(25)))
    assert h.evidence["ref_mean"] == pytest.approx(0.0) and h.evidence[
        "live_mean"
    ] == pytest.approx(-0.005)


def test_too_few_live_days_is_insufficient_never_a_pass():
    h = dg.assess(REF, noise(5, -0.01, 19))  # 19 days of a disaster is still too few to judge
    assert (
        h.status == "INSUFFICIENT"
        and "19 live days" in h.reasons[0]
        and "at least 20" in h.reasons[0]
    )
    assert (
        dg.assess(REF, noise(5, -0.01, 20)).status != "INSUFFICIENT"
    )  # exactly the minimum is enough


def test_a_reference_too_short_or_flat_to_judge_against_is_insufficient_too():
    assert dg.assess([0.001] * 10, noise(6, 0.0, 60)).status == "INSUFFICIENT"
    flat = dg.assess([0.0] * 100, noise(6, 0.0, 60))
    assert flat.status == "INSUFFICIENT" and "no variation" in flat.reasons[0]


def test_a_drawdown_much_deeper_than_the_references_is_degraded_even_when_the_mean_is_fine():
    ref = noise(7, 0.001, 750, vol=0.005)
    ref_dd = dg.drawdown(ref)
    live = (
        [0.006] * 30 + [-0.02] * 6 + [0.006] * 24
    )  # a sharp loss streak inside a period that still averages well above the reference
    h = dg.assess(ref, live)
    assert h.evidence["z"] > 0  # the mean is fine
    assert h.evidence["live_drawdown"] < 1.5 * ref_dd < 0
    assert h.status == "DEGRADED" and len(h.reasons) == 1 and "drawdown" in h.reasons[0]


def test_only_the_most_recent_window_is_judged():
    old_disaster_then_recovery = noise(8, -0.01, 100) + noise(9, 0.0008, 60)
    assert dg.assess(REF, old_disaster_then_recovery, window=60).status == "OK"
    assert dg.assess(REF, old_disaster_then_recovery, window=160).status == "DEGRADED"
    assert dg.assess(REF, old_disaster_then_recovery, window=60).evidence["live_days"] == 60


def test_drawdown_is_the_worst_peak_to_trough_fall_of_the_compounded_curve():
    assert dg.drawdown([0.1, -0.1]) == pytest.approx(-0.1)  # 1.1 then 0.99
    assert dg.drawdown([0.1, 0.1]) == 0.0 and dg.drawdown([]) == 0.0
    assert dg.drawdown([-0.5, 1.0, -0.5]) == pytest.approx(
        -0.5
    )  # 0.5, 1.0, 0.5: the second fall from the new peak is the deepest


def test_the_rolling_sharpe_is_reported_beside_the_references():
    h = dg.assess(REF, noise(4, 0.0008, 60))
    assert h.evidence["live_sharpe"] is not None and h.evidence["ref_sharpe"] is not None
    flat_live = dg.assess(REF, [0.0] * 40)
    assert flat_live.evidence["live_sharpe"] is None  # no variation: undefined, not zero


def test_thresholds_are_validated():
    for bad in (
        dg.Thresholds(watch_z=-3.0, degraded_z=-2.0),
        dg.Thresholds(min_days=1),
        dg.Thresholds(drawdown_multiple=0.5),
    ):
        with pytest.raises(ValueError):
            dg.assess(REF, noise(4, 0.0, 60), thresholds=bad)


def test_threshold_edges_and_messages():
    cases = [
        (dg.Thresholds(watch_z=-2.0, degraded_z=-2.0), "degraded_z < watch_z < 0"),
        (dg.Thresholds(watch_z=0.0, degraded_z=-2.0), "degraded_z < watch_z < 0"),
        (dg.Thresholds(watch_z=0.5, degraded_z=-2.0), "degraded_z < watch_z < 0"),
        (dg.Thresholds(min_days=4), "at least 5"),
        (dg.Thresholds(min_reference_days=4), "at least 5"),
    ]
    for bad, msg in cases:
        with pytest.raises(ValueError, match=msg):
            bad.validate()
    with pytest.raises(ValueError, match="drawdown_multiple must be at least 1"):
        dg.Thresholds(drawdown_multiple=0.99).validate()
    dg.Thresholds(min_days=5, min_reference_days=5, drawdown_multiple=1.0).validate()


def test_evidence_keys_values_and_defaults():
    import statistics

    ref = noise(11, 0.002, 100)  # non-zero mean so sign slips show
    h = dg.assess(ref, noise(12, 0.002, 100))
    assert h.evidence["live_days"] == 60 and h.evidence["ref_days"] == 100  # default window 60
    assert set(h.evidence) == {
        "live_days", "ref_days", "live_mean", "ref_mean", "ref_std", "z",
        "live_drawdown", "ref_drawdown", "live_sharpe", "ref_sharpe",
    }  # fmt: skip
    assert h.evidence["ref_std"] == pytest.approx(statistics.stdev(ref))
    live = h.evidence["live_mean"]
    assert h.evidence["z"] == pytest.approx(
        (live - statistics.mean(ref)) / (statistics.stdev(ref) / math.sqrt(60))
    )
    assert h.evidence["ref_drawdown"] == dg.drawdown(ref)


def test_reference_length_edge_and_reason_texts():
    short = dg.assess([0.01, -0.01] * 29, noise(6, 0, 60))
    assert short.reasons == ["the reference has 58 days: at least 60 are needed to compare against"]
    assert dg.assess([0.01, -0.01] * 30, noise(6, 0, 60)).status != "INSUFFICIENT"
    flat = dg.assess([0.0] * 100, noise(6, 0, 60))
    assert flat.reasons == [
        "the reference has no variation, so a live result cannot be compared with it"
    ]
    few = dg.assess(REF, [0.0] * 3)
    assert few.reasons == ["only 3 live days: at least 20 are needed to judge"]


def test_z_exactly_on_a_threshold_trips_it_and_reasons_are_worded():
    live = noise(3, -0.004, 60)
    z = dg.assess(REF, live).evidence["z"]
    d = dg.assess(REF, live, thresholds=dg.Thresholds(degraded_z=z, watch_z=z / 2))
    assert d.status == "DEGRADED"
    assert (
        d.reasons[0].startswith("mean return ")
        and "standard errors below the reference's" in d.reasons[0]
    )
    w = dg.assess(REF, live, thresholds=dg.Thresholds(degraded_z=z - 1, watch_z=z))
    assert w.status == "WATCH" and "standard errors below the reference's" in w.reasons[0]


def test_drawdown_rule_edges():
    ref = [0.001, 0.002] * 50  # never falls: no drawdown to compare with
    live = [0.01] * 30 + [-0.01] + [0.01] * 29
    assert dg.assess(ref, live).status == "OK"
    wavy = [0.01, -0.02] * 30
    same = dg.assess(wavy, list(wavy), thresholds=dg.Thresholds(drawdown_multiple=1.0))
    assert same.evidence["live_drawdown"] == same.evidence["ref_drawdown"] and same.status == "OK"
