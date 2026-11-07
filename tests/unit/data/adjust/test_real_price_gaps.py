"""Factors derived from NSE subject text must match how the market actually repriced.
Raw closes below are real NSE bhavcopy values (prior session close vs ex-date close)."""

from decimal import Decimal as D

import pytest

from algo.data.adjust.factors import split_factor
from algo.data.providers.nse_corporate_actions import parse_subject

BAJAJ_SPLIT = "Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share"
CASES = [  # symbol, ex-date, [NSE subjects], prior raw close, ex-date close
    ("BAJFINANCE", "2025-06-16", ["Bonus 4:1", BAJAJ_SPLIT], "9331.00", "938.00"),
    ("RELIANCE", "2024-10-28", ["Bonus 1:1"], "2655.70", "1334.35"),
    ("HDFCBANK", "2025-08-26", ["Bonus 1:1"], "1964.10", "973.40"),
    ("WIPRO", "2024-12-03", ["Bonus 1:1"], "584.55", "291.65"),
]


@pytest.mark.parametrize(("sym", "ex", "subjects", "prior", "exclose"), CASES)
def test_factor_matches_observed_market_repricing(sym, ex, subjects, prior, exclose):
    expected = D(1)
    for s in subjects:
        for comp in parse_subject(s):
            assert comp.status == "ok"
            expected *= split_factor(comp.num, comp.den)
    observed = D(exclose) / D(prior)
    # one-day market move is a few %; a wrong convention would be off by 2x or more
    assert abs(observed / expected - 1) < D("0.02"), (sym, ex, observed, expected)
