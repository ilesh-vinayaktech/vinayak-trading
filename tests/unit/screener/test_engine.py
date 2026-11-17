from decimal import Decimal as D

import pytest

from algo.screener.engine import FIELDS, ScreenError, run
from algo.screener.engine import Condition as C

ROWS = [
    {"symbol": "A", "pe": D(10), "roe": D(20), "segment": "large", "rsi_14": None},
    {"symbol": "B", "pe": D(30), "roe": D(25), "segment": "mid", "rsi_14": D(25)},
    {"symbol": "C", "pe": None, "roe": D(5), "segment": "large", "rsi_14": D(60)},
]


def syms(conds, **kw):
    rows, total = run(ROWS, conds, **kw)
    return [r["symbol"] for r in rows], total


def test_every_operator():
    assert syms([C("pe", "gt", 10)])[0] == ["B"]
    assert syms([C("pe", "gte", 10)])[0] == ["A", "B"]
    assert syms([C("pe", "lt", 30)])[0] == ["A"]
    assert syms([C("pe", "lte", 30)])[0] == ["A", "B"]
    assert syms([C("pe", "eq", 10)])[0] == ["A"]
    assert syms([C("pe", "ne", 10)])[0] == ["B"]
    assert syms([C("pe", "between", [5, 15])])[0] == ["A"]
    assert syms([C("segment", "eq", "mid")])[0] == ["B"]
    assert syms([C("segment", "ne", "mid")])[0] == ["A", "C"]
    assert syms([C("segment", "in", ["mid", "large"])])[1] == 3


def test_missing_values_never_match_even_negated():
    assert "C" not in syms([C("pe", "ne", 10)])[0]
    assert syms([C("rsi_14", "lt", 100)])[0] == ["B", "C"]


def test_all_vs_any_and_no_conditions_matches_nothing():
    both = [C("pe", "lte", 10), C("roe", "gte", 25)]
    assert syms(both, match="all")[1] == 0
    assert syms(both, match="any")[1] == 2
    assert syms([])[1] == 0


def test_sorting_puts_missing_last_and_limit_keeps_total():
    conds = [C("roe", "gte", 0)]
    assert syms(conds, sort="pe")[0] == ["B", "A", "C"]
    assert syms(conds, sort="pe", descending=False)[0] == ["A", "B", "C"]
    rows, total = run(ROWS, conds, sort="roe", limit=1)
    assert [r["symbol"] for r in rows] == ["B"] and total == 3


@pytest.mark.parametrize(
    "bad",
    [
        C("nope", "gt", 1), C("pe", "like", 1), C("pe", "gt", "abc"), C("pe", "gt", "NaN"),
        C("pe", "between", [1]), C("pe", "between", [5, 1]), C("segment", "gt", "x"), C("segment", "in", "large"),
    ],
)  # fmt: skip
def test_bad_conditions_are_refused(bad):
    with pytest.raises(ScreenError):
        run(ROWS, [bad])


def test_bad_sort_or_match_is_refused():
    with pytest.raises(ScreenError):
        run(ROWS, [C("pe", "gt", 1)], sort="nope")
    with pytest.raises(ScreenError):
        run(ROWS, [C("pe", "gt", 1)], match="some")


def test_fields_cover_ratios_technicals_and_profile():
    kinds = {f.kind for f in FIELDS.values()}
    assert (
        kinds == {"fundamental", "technical", "profile", "smart_money", "score"}
        and "roce" in FIELDS
        and "rsi_14" in FIELDS
    )
