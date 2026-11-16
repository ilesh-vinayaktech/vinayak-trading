# ruff: noqa: E501
"""The correlation of strategies' daily returns: do two strategies that passed move together (so combining them adds little) or apart."""

import random

import pytest

from algo.portfolio import strategy_correlation as sc


def noise(seed, n=250, drift=0.0005):
    r = random.Random(seed)
    return [drift + r.gauss(0, 0.01) for _ in range(n)]


def test_the_matrix_is_symmetric_one_on_the_diagonal_and_flags_near_copies():
    a = noise(1)
    book = {"A": a, "B": [x * 1.5 + 0.0001 for x in a], "C": noise(2)}  # B is A scaled: a near copy
    m = sc.matrix(book)
    assert m["A"]["A"] == pytest.approx(1.0) and m["A"]["B"] == pytest.approx(m["B"]["A"])
    assert m["A"]["B"] == pytest.approx(1.0) and abs(m["A"]["C"]) < 0.3
    assert sc.near_copies(m, 0.9) == [
        ("A", "B", pytest.approx(1.0))
    ]  # only the pair that moves together


def test_series_of_different_length_are_cut_to_their_common_end_and_a_flat_one_has_no_correlation():
    a, b = noise(1, 250), noise(2, 200)
    m = sc.matrix({"A": a, "B": b})
    assert m["A"]["B"] is not None  # compared over the last 200 days both have
    flat = sc.matrix({"A": a, "F": [0.0] * 250})
    assert flat["A"]["F"] is None


def test_the_text_report_lists_the_matrix_and_the_pairs_worth_a_second_look():
    a = noise(3)
    text = sc.report({"X": a, "Y": [v * 2 for v in a], "Z": noise(4)}, threshold=0.9)
    assert "X" in text and "Y" in text and "move together" in text and "X and Y" in text
    assert sc.report({"X": a, "Z": noise(4)}, threshold=0.9).count(
        "move together"
    ) == 0 or "no pair" in sc.report({"X": a, "Z": noise(4)}, threshold=0.9)
