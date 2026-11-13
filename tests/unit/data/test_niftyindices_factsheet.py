from datetime import date, timedelta

import pytest

from algo.data.providers.niftyindices_factsheet import FactsheetError, build_checks, parse

SHEET = """                October 30, 2026
 Index Variant: Nifty IT Total Returns Index.
                           QTD    YTD 1 Year 5 Years
        Returns (%) #                            Inception
        Price Return   17.69 -13.93 -8.70  -1.07      20.63
        Total Return   18.06 -12.48 -7.13   0.93           -
"""


def test_parse_reads_the_date_and_both_rows_and_ignores_the_variant_sentence():
    as_of, rows = parse(SHEET)
    assert as_of == date(2026, 10, 30)
    assert rows["price"] == ("17.69", "-13.93", "-8.70", "-1.07", "20.63")
    assert rows["total"] == ("18.06", "-12.48", "-7.13", "0.93", "-")


@pytest.mark.parametrize("text", ["no date here", "October 30, 2026\n Price Return 1 2 3 4 5"])
def test_parse_refuses_a_sheet_without_a_date_or_a_row(text):
    with pytest.raises(FactsheetError):
        parse(text)


def sessions(first, last):
    d = first
    while d <= last:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def test_checks_use_the_convention_of_the_existing_sheets_and_roll_bases_back_to_a_session():
    days = set(sessions(date(2015, 1, 1), date(2026, 10, 30)))
    c = {x["label"]: x for x in build_checks(date(2026, 10, 30), ("1", "2", "3", "4", "-"), days)}
    assert c["QTD"]["base"] == "2026-09-30" and c["YTD"]["base"] == "2025-12-31"
    assert c["1 year"]["base"] == "2025-10-31"
    assert (
        c["5 years (CAGR)"]["base"] == "2021-10-29"
    )  # 2021-10-30 is a Saturday: the session before
    assert c["5 years (CAGR)"]["kind"] == "cagr" and c["QTD"]["tolerance_pp"] == "0.005"


def test_checks_skip_unpublished_figures_and_bases_before_the_stored_history():
    days = set(sessions(date(2024, 1, 1), date(2026, 10, 30)))
    got = build_checks(date(2026, 10, 30), ("1", "2", "-", "4", "5"), days)
    assert [x["label"] for x in got] == [
        "QTD",
        "YTD",
    ]  # 1 year not published; 5 years starts before 2024


def test_a_29_february_end_date_steps_back_to_28_february():
    days = set(sessions(date(2015, 1, 1), date(2028, 2, 29)))
    c = {x["label"]: x for x in build_checks(date(2028, 2, 29), ("1", "2", "3", "4", "5"), days)}
    assert c["1 year"]["base"] == "2027-03-01"  # 2027-02-28 + 1 day
    assert c["5 years (CAGR)"]["base"] == "2023-02-28"  # 2028-02-29 minus 5 years is 2023-02-28
