# ruff: noqa: E501
"""The swing score: each stock ranked against the others on trend, participation, smart money and quality, combined with fixed weights. A missing figure is
never read as zero: a stock with no deals has no smart-money component, and the composite is re-weighted over what exists."""

from decimal import Decimal as D

import pytest

from algo.screener.engine import FIELDS
from algo.screener.score import COMPONENTS, WEIGHTS, Scored, attach, score_universe


def row(iid, **over):
    base = {
        "instrument_id": iid, "chg_1m": D(2), "chg_3m": D(5), "price_vs_sma50": D(3), "pct_from_52w_high": D(-10), "rsi_14": D(55), "adx_14": D(22),
        "volume_ratio": D(1), "delivery_vs_avg": D(1), "delivery_pct": D(45), "turnover_cr": D(25),
        "deal_net_30d": None, "insider_net_90d": None, "fii_change": None, "dii_change": None, "promoter_change": None,
        "roe": D(15), "roce": D(18), "profit_growth": D(10), "debt_to_equity": D("0.5"),
    }  # fmt: skip
    return {**base, **over}


def universe():
    strong = row(1, chg_1m=D(15), chg_3m=D(30), price_vs_sma50=D(12), pct_from_52w_high=D(-1), volume_ratio=D("2.5"), delivery_vs_avg=D("1.8"), delivery_pct=D(70),
                 deal_net_30d=D(50), insider_net_90d=D(5), fii_change=D("1.5"), roe=D(35), roce=D(40), profit_growth=D(40), debt_to_equity=D("0.05"))  # fmt: skip
    weak = row(2, chg_1m=D(-12), chg_3m=D(-25), price_vs_sma50=D(-10), pct_from_52w_high=D(-45), volume_ratio=D("0.4"), delivery_vs_avg=D("0.5"), delivery_pct=D(15),
               deal_net_30d=D(-40), insider_net_90d=D(-3), fii_change=D("-1.5"), roe=D(-5), roce=D(2), profit_growth=D(-30), debt_to_equity=D(3))  # fmt: skip
    mid = [row(i) for i in range(3, 12)]
    return [strong, weak, *mid]


def by_id(rows):
    return {s.instrument_id: s for s in score_universe(rows)}


def test_the_strongest_stock_on_everything_scores_highest_and_the_weakest_lowest():
    got = by_id(universe())
    middle = [s.composite for i, s in got.items() if i not in (1, 2)]
    assert got[1].composite > max(middle) >= min(middle) > got[2].composite
    assert got[1].composite > 85 and got[2].composite < 15
    assert set(got[1].components) == set(COMPONENTS)
    assert all(0 <= v <= 100 for v in got[1].components.values() if v is not None)


def test_the_weights_add_up_to_one_and_name_every_component():
    assert set(WEIGHTS) == set(COMPONENTS) and sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_a_missing_figure_is_not_a_zero_and_the_composite_uses_what_exists():
    rows = universe()
    got = by_id(rows)
    assert (
        got[5].components["smart_money"] is None
    )  # no deals, no insider, no holding change: unknown, not zero
    assert got[5].composite is not None  # still scored on the other three components
    bare = row(20, delivery_vs_avg=None, delivery_pct=None, volume_ratio=None)
    assert by_id([*rows, bare])[20].components["participation"] is None


def test_too_few_components_gives_no_composite_instead_of_a_guess():
    bare = {"instrument_id": 99, "chg_1m": D(3), "turnover_cr": D(25)}
    got = by_id([*universe(), bare])
    assert got[99].composite is None and got[99].components["trend"] is not None


def test_net_buying_ranks_above_net_selling_and_a_stock_with_no_deals_has_no_smart_money_figure():
    base = [row(i) for i in range(3, 12)]
    buyer, seller, quiet = row(1, deal_net_30d=D(80)), row(2, deal_net_30d=D(-80)), row(12)
    got = by_id([buyer, seller, quiet, *base])
    assert got[1].components["smart_money"] > got[2].components["smart_money"]
    assert got[12].components["smart_money"] is None


def test_setup_flags_name_the_pattern_and_the_reasons_are_the_top_drivers():
    got = by_id(universe())
    assert "Breakout setup" in got[1].flags and "Accumulation" in got[1].flags
    assert "Breakout setup" not in got[2].flags
    over = by_id([row(1, rsi_14=D(82)), *[row(i) for i in range(2, 10)]])
    assert "Overbought" in over[1].flags
    assert 1 <= len(got[1].reasons) <= 3 and all(isinstance(r, str) and r for r in got[1].reasons)


def test_it_does_not_change_its_input_and_the_order_of_rows_does_not_matter():
    rows = universe()
    before = [dict(r) for r in rows]
    a = score_universe(rows)
    assert rows == before
    b = score_universe(list(reversed(rows)))
    assert {s.instrument_id: s.composite for s in a} == {s.instrument_id: s.composite for s in b}


def test_a_universe_of_one_or_none_is_handled():
    assert score_universe([]) == []
    (only,) = score_universe([row(1)])
    assert isinstance(only, Scored) and only.composite == pytest.approx(
        50.0
    )  # alone, it ranks at the middle on everything


def test_attach_adds_the_score_fields_leaves_missing_ones_out_and_registers_them_as_a_kind_a_strategy_cannot_use():
    rows = universe()
    out = {r["instrument_id"]: r for r in attach(rows)}
    assert (
        out[1]["score"] > 85
        and out[1]["score_smart_money"] > 50
        and "Breakout setup" in out[1]["setup"]
        and out[1]["score_why"]
    )
    assert (
        "score_smart_money" not in out[5] and "setup" not in out[5]
    )  # mid stocks: no deals, no flags: absent, not zero
    assert (
        all(r["instrument_id"] == i for i, r in out.items()) and "score" not in rows[0]
    )  # the input is not changed
    for key in (
        "score",
        "score_trend",
        "score_participation",
        "score_smart_money",
        "score_quality",
        "setup",
        "score_why",
    ):
        assert (
            FIELDS[key].kind == "score"
        )  # strategies accept only technical and fundamental fields, so a score cannot drive one yet
    assert FIELDS["setup"].unit == "text" and FIELDS["score"].unit == "x"


def test_a_thinly_traded_stock_gets_no_score_and_does_not_distort_the_ranking_of_the_rest():
    thin = row(
        50, chg_1m=D(90), chg_3m=D(200), price_vs_sma50=D(60), turnover_cr=D("0.2")
    )  # a spectacular mover nobody can trade
    liquid = [row(i, turnover_cr=D(25)) for i in range(3, 12)]
    with_thin = {s.instrument_id: s for s in score_universe([thin, *liquid])}
    without = {s.instrument_id: s for s in score_universe(liquid)}
    assert with_thin[50].composite is None and all(
        v is None for v in with_thin[50].components.values()
    )
    assert (
        with_thin[3].composite == without[3].composite
    )  # its presence changes nobody else's score
    unknown = {
        k: v for k, v in row(51).items() if k != "turnover_cr"
    }  # liquidity unknown: we cannot say it can be traded
    assert {s.instrument_id: s for s in score_universe([unknown, *liquid])}[51].composite is None
