from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.data.providers.nse_index_monthly import (
    Constituent,
    extract_words,
    parse_snapshot,
)  # fmt: skip

FIX = Path(__file__).parents[2] / "data/nse_index_monthly"


def snap(name):
    return parse_snapshot(extract_words((FIX / name).read_bytes()))


def test_nifty_50_has_fifty_rows_that_sum_to_about_100_and_no_problems():
    s = snap("NIFTY_50_Mar2020.pdf")
    assert (s.index_name, s.component, s.as_of) == ("NIFTY 50", "NIFTY_50", date(2020, 3, 31))
    assert len(s.rows) == 50 and s.problems == ()
    assert sum(r.weight for r in s.rows) == pytest.approx(D("100"), abs=D("0.5"))
    assert len({r.symbol for r in s.rows}) == 50


def test_a_row_carries_all_its_fields_exactly():
    s = snap("NIFTY_50_Mar2020.pdf")
    ports = next(r for r in s.rows if r.symbol == "ADANIPORTS")
    assert ports == Constituent(
        "ADANIPORTS", "Adani Ports and Special Economic Zone Ltd.", "SERVICES",
        D("251.30"), D("19402"), D("0.54"), 1,
    )  # fmt: skip


def test_wrapped_names_ampersands_and_pages_are_handled():
    s = snap("NIFTY_Midcap_100_Mar2020.pdf")
    assert (s.index_name, s.component, len(s.rows), s.problems) == (
        "NIFTY Midcap 100",
        "MIDCAP_100",
        100,
        (),
    )
    by = {r.symbol: r for r in s.rows}
    assert by["ABFRL"].name == "Aditya Birla Fashion and Retail Ltd." and by["ABFRL"].weight == D(
        "1.03"
    )
    assert (
        by["BBTC"].name == "Bombay Burmah Trading Corporation Ltd."
    )  # name wrapped over two lines
    assert max(r.page for r in s.rows) == 4 and min(r.page for r in s.rows) == 1
    assert by["AUBANK"].industry == "FINANCIAL SERVICES" and by["AUBANK"].index_mcap == D("9196")
    assert any("&" in r.industry for r in s.rows)  # HTML entities are decoded


def test_the_nifty_200_report_lists_201_on_2020_03_31_and_the_extra_one_is_a_dvr_share():
    s = snap("NIFTY_200_Mar2020.pdf")
    assert s.component == "NIFTY_200" and len(s.rows) == 201 and s.problems == ()
    assert "TATAMTRDVR" in {r.symbol for r in s.rows}  # not in Nifty 50 / Next 50 / Midcap 100
    symbols = {r.symbol for r in s.rows}
    parts = {
        r.symbol
        for n in ("NIFTY_50_Mar2020.pdf", "NIFTY_Midcap_100_Mar2020.pdf")
        for r in snap(n).rows
    }
    assert parts <= symbols  # the components that we have are all inside it


def test_a_non_constituents_pdf_is_refused():
    with pytest.raises(ValueError, match="not a constituents report"):
        parse_snapshot([[(10.0, 10.0, 20.0, 20.0, "Hello")]])


def make_page(rows, title="Constituents of NIFTY Test", date_line="March 31, 2020"):
    """Synthetic page: header, then rows of (symbol, name, industry, price, mcap, weight)."""
    words = [(384.0, 57.0, 400.0, 66.0, "Constituents"), (451.0, 57.0, 460.0, 66.0, "of"),
             (464.0, 57.0, 490.0, 66.0, "NIFTY"), (505.0, 57.0, 530.0, 66.0, "Test"),
             (500.0, 79.0, 520.0, 88.0, "March"), (531.0, 79.0, 545.0, 88.0, "31,"),
             (546.0, 79.0, 570.0, 88.0, "2020"), (133.0, 116.0, 160.0, 124.0, "Security"),
             (289.0, 117.0, 320.0, 124.0, "Industry"), (519.0, 112.0, 560.0, 120.0, "Weightage")]  # fmt: skip
    if title != "Constituents of NIFTY Test":
        words = [w for w in words if w[1] != 57.0]
    if date_line == "":
        words = [w for w in words if w[1] != 79.0]
    y = 142.0
    for sym, name, ind, price, mcap, wt in rows:
        words += [(28.0, y + 2, 60.0, y + 9, sym), (105.0, y, 180.0, y + 8, name),
                  (230.0, y + 2, 300.0, y + 9, ind), (425.0, y, 450.0, y + 8, price),
                  (495.0, y, 520.0, y + 8, mcap), (554.0, y, 570.0, y + 8, wt)]  # fmt: skip
        y += 22.0
    return words


def test_bad_records_duplicates_and_weight_sums_are_reported_not_hidden():
    page = make_page([("AAA", "Alpha", "POWER", "10.00", "100", "60.00"),
                      ("AAA", "Alpha again", "POWER", "10.00", "100", "30.00")])  # fmt: skip
    page.append((28.0, 300.0, 60.0, 308.0, "ORPHAN"))  # a symbol with no numbers
    s = parse_snapshot([page])
    assert [r.symbol for r in s.rows] == ["AAA", "AAA"]
    assert "page 1 ORPHAN: expected price, mcap, weight; got 0 numbers" in s.problems
    assert "duplicate symbol AAA" in s.problems
    assert "weights sum to 90.00, not ~100" in s.problems


def test_an_empty_body_is_a_problem_and_header_only_extra_pages_are_skipped():
    s = parse_snapshot([make_page([]), []])
    assert s.rows == () and s.problems == ("no constituents found",)
    ok = parse_snapshot([make_page([("AAA", "Alpha", "POWER", "10.00", "1,000", "100.00")]), []])
    assert ok.problems == () and ok.rows[0].index_mcap == D("1000")  # thousands separators


def test_digits_inside_an_industry_label_are_not_mistaken_for_prices():
    page = make_page(
        [
            (
                "BAJAJ-AUTO",
                "Bajaj Auto Ltd.",
                "AUTOMOBILES - 2 AND 3 WHEELERS",
                "2791.20",
                "37961",
                "100.00",
            )
        ]
    )
    page = [w for w in page if w[4] != "BAJAJ-AUTO"] + [(28.0, 144.0, 60.0, 151.0, "BAJAJ-AUTO")]
    page += [(289.0, 144.0, 292.0, 151.0, "2"), (319.0, 144.0, 322.0, 151.0, "3"),
             (393.0, 117.0, 410.0, 124.0, "Close")]  # fmt: skip
    s = parse_snapshot([page])
    assert s.problems == () and s.rows[0].price == D("2791.20") and s.rows[0].weight == D("100.00")
    assert "2" in s.rows[0].industry and "3" in s.rows[0].industry
