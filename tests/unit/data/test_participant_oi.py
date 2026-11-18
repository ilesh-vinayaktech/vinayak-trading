from datetime import date

import pytest

from algo.data.participant_oi import parse

FILE = (
    b'""Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Nov 17, 2026"",,,,\n'
    b"Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short       ,Total Long Contracts      \n"
    b"Client,170907,115613,3180794,391846,11749181\n"
    b"FII,65568,130691,3629602,2645357,6157158\n"
    b"TOTAL,318229,318229,7990802,7990802,23579725\n"
)


def test_the_fii_row_gives_index_futures_long_and_short_for_the_day_in_the_title():
    assert parse(FILE) == (date(2026, 11, 17), 65568, 130691)


def test_a_file_with_no_title_line_takes_the_day_that_was_asked_for():
    body = FILE.split(b"\n", 1)[1]
    assert parse(body, date(2018, 6, 13)) == (date(2018, 6, 13), 65568, 130691)
    with pytest.raises(ValueError, match="no date"):
        parse(body)


def test_a_file_without_a_header_or_an_fii_row_is_refused():
    with pytest.raises(ValueError, match="no header"):
        parse(b"not a participant file\n")
    with pytest.raises(ValueError, match="no FII row"):
        parse(FILE.replace(b"FII,", b"XXX,"))


def test_older_files_spell_the_month_out():
    old = FILE.replace(b"as on Nov 17, 2026", b"as on June 01, 2017")
    assert parse(old) == (date(2017, 6, 1), 65568, 130691)


def test_a_count_written_with_commas_and_decimals_is_read():
    assert parse(FILE.replace(b"65568,130691", b'"65,568.00","130,691.00"')) == (
        date(2026, 11, 17),
        65568,
        130691,
    )
