# ruff: noqa: E501
"""The market zone: fear/greed from many independent signals, each a percentile of its own trailing history, and a trend/volatility regime. Pure functions,
point in time: the answer for day T must not change if later days are cut off."""

import random

import pytest

from algo.market.zone import (
    Series,
    components,
    fear_greed,
    pct_rank,
    regime,
    score_all,
    zone_label,
)

N = 400


MOVE = 150  # the last days of the synthetic market are a strong move; before that it is flat


def rising(n=N, drift=0.0015, noise=0.004, seed=1, start=100.0):
    """A random walk that is flat for the first n-MOVE days and drifts by `drift` a day for the last MOVE."""
    rnd, x, out = random.Random(seed), start, []
    for i in range(n):
        x *= 1 + (drift if i >= n - MOVE else 0.0) + rnd.uniform(-noise, noise)
        out.append(x)
    return out


def ramp(n, lo, hi, sign, seed):
    """Around `lo` for the flat days, then moving to `hi` (sign 1) or away from it (sign -1) over the last MOVE days."""
    rnd = random.Random(seed)
    return [
        (lo if i < n - MOVE else lo + sign * (hi - lo) * (i - (n - MOVE)) / MOVE)
        + rnd.uniform(-2, 2)
        for i in range(n)
    ]


def market(up=True, n=N, seed=1):
    """A synthetic market that is flat, then rallies (up) or sells off (down): the index trends, VIX falls or rises, breadth widens or collapses, highs
    or lows dominate, stocks beat or lose to bonds, and risk appetite swings with it."""
    sign = 1 if up else -1
    breadth = [min(95.0, max(5.0, b)) for b in ramp(n, 50, 90, sign, seed)]
    return Series(
        index=rising(n, drift=sign * 0.003, seed=seed),
        vix=rising(n, drift=-sign * 0.01, noise=0.01, seed=seed + 1, start=18.0),
        bond=rising(n, drift=0.0002, noise=0.001, seed=seed + 2),
        high_beta=rising(n, drift=sign * 0.004, seed=seed + 3),
        low_vol=rising(n, drift=sign * 0.001, seed=seed + 4),
        small=rising(n, drift=sign * 0.004, seed=seed + 5),
        large=rising(n, drift=sign * 0.002, seed=seed + 6),
        pct_above_50=breadth,
        pct_above_200=[min(95.0, max(5.0, b - 5)) for b in breadth],
        highs=[int(max(0, h)) for h in ramp(n, 20, 80, sign, seed + 7)],
        lows=[int(max(0, h)) for h in ramp(n, 20, 80, -sign, seed + 8)],
        advancers=[int(a) for a in ramp(n, 1000, 1500, sign, seed + 9)],
        decliners=[int(a) for a in ramp(n, 1000, 1500, -sign, seed + 10)],
    )


def fields(s: Series) -> dict:
    return {f: getattr(s, f) for f in s.__dataclass_fields__}


def cut(s: Series, k: int) -> Series:
    return Series(**{f: v[:k] for f, v in fields(s).items()})


def test_pct_rank_is_a_percentile_of_the_history_and_ties_take_the_middle():
    hist = [1.0, 2.0, 3.0, 4.0]
    assert pct_rank(hist, 10.0) == 100.0 and pct_rank(hist, -1.0) == 0.0
    assert pct_rank(hist, 2.5) == 50.0
    assert pct_rank([5.0, 5.0, 5.0], 5.0) == 50.0
    assert pct_rank(hist, 3.0) < pct_rank(hist, 3.5)


def test_a_rising_market_reads_greedy_and_a_falling_one_fearful():
    up, down = fear_greed(components(market(True))), fear_greed(components(market(False)))
    assert up is not None and down is not None
    assert up > 65 and down < 35 and up - down > 30
    assert zone_label(up) in ("Greed", "Extreme greed")
    assert zone_label(down) in ("Fear", "Extreme fear")


def test_every_component_is_between_zero_and_one_hundred_and_named():
    comps = components(market(True))
    named = {"momentum", "breadth", "highs_lows", "volatility", "advance_decline"}
    named |= {"stocks_vs_bonds", "risk_appetite", "size_appetite"}
    assert named <= set(comps)
    assert all(v is None or 0 <= v <= 100 for v in comps.values())


def test_the_answer_for_a_day_does_not_change_when_later_days_are_cut_off():
    s = market(True)
    for k in (150, 250, 399):
        assert components(s, at=k) == components(cut(s, k + 1)), k  # no lookahead


def test_too_little_history_gives_no_score_instead_of_a_guess():
    short = cut(market(True), 30)
    assert fear_greed(components(short)) is None
    assert all(v is None for v in components(short).values())


def test_a_missing_signal_is_none_and_the_score_uses_the_rest_but_needs_enough_of_them():
    s = market(True)
    no_bonds = Series(**{**fields(s), "bond": []})
    comps = components(no_bonds)
    assert comps["stocks_vs_bonds"] is None and fear_greed(comps) is not None
    full = components(s)
    barely = {k: (v if i < 3 else None) for i, (k, v) in enumerate(full.items())}
    assert fear_greed(barely) is None


@pytest.mark.parametrize(
    ("score", "label"),
    [
        (0, "Extreme fear"),
        (24.9, "Extreme fear"),
        (25, "Fear"),
        (44.9, "Fear"),
        (45, "Neutral"),
        (55, "Neutral"),
        (55.1, "Greed"),
        (75, "Greed"),
        (75.1, "Extreme greed"),
        (100, "Extreme greed"),
    ],
)
def test_the_zone_label_boundaries(score, label):
    assert zone_label(score) == label


def test_the_regime_says_bull_bear_or_sideways_and_how_calm():
    bull, bear = regime(market(True)), regime(market(False))
    assert bull.trend == "BULL" and bear.trend == "BEAR"
    assert bull.volatility in ("CALM", "NORMAL") and bear.volatility in ("NORMAL", "STRESSED")
    flat = Series(**{**fields(market(True)), "index": [100 + (i % 7) * 0.1 for i in range(N)]})
    assert regime(flat).trend == "SIDEWAYS"
    assert regime(cut(market(True), 100)).trend == "UNKNOWN"  # not enough for a 200-day average


def test_scoring_every_day_at_once_gives_the_same_answers_as_one_day_at_a_time():
    s = market(True)
    everyday = score_all(s)
    assert len(everyday) == N
    for k in (0, 59, 130, 200, 300, N - 1):
        assert everyday[k] == components(s, at=k), k
