from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.core.calendar import nse
from algo.data.bars import Freq
from algo.data.providers.base import ParseError
from algo.data.providers.nse_bhavcopy import NseBhavcopy

D0 = date(2026, 11, 5)
RAW = (Path(__file__).parents[2] / "data/nse/sec_bhavdata_full_05112026.csv").read_bytes()  # real
P = NseBhavcopy(lambda url: RAW, nse())


def test_real_file_main_board_only_with_open_utc_ts_and_extras():
    bars = {b.symbol: b for b in P.parse("bhav", D0, RAW)}
    assert set(bars) == {"RELIANCE", "TCS", "360ONE", "21STCENMGM", "AGSTRA"}  # GS/SM skipped
    r = bars["RELIANCE"]
    assert r.ts == datetime(2026, 11, 5, 3, 45, tzinfo=UTC)  # 09:15 IST session open
    assert (r.open, r.high, r.low, r.close, r.volume) == (
        D("1324.00"), D("1325.00"), D("1303.70"), D("1313.40"), D("19479324")
    )  # fmt: skip
    assert dict(r.extra) == {
        "series": "EQ",
        "prev_close": D("1311.00"),
        "delivery_qty": D("9060662"),
    }
    assert bars["21STCENMGM"].extra["series"] == "BE" and bars["AGSTRA"].extra["series"] == "BZ"
    assert bars["AGSTRA"].extra["delivery_qty"] is None  # '-' in file


def test_fetch_url_freq_flags():
    seen = []
    p = NseBhavcopy(lambda u: seen.append(u) or b"x", nse())
    assert p.fetch("bhav", D0) == b"x"
    assert seen == [
        "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_05112026.csv"
    ]
    assert p.supports_corrections() is False and p.name == "nse" and p.freq("bhav") is Freq.D1


def test_prev_close_dash_is_none():
    raw = RAW.replace(b"1311.00", b"-", 1)
    assert next(iter(P.parse("bhav", D0, raw))).extra["prev_close"] is None


def test_holiday_with_stale_file_is_not_published_even_if_calendar_says_closed():
    """On a calendar holiday NSE re-serves the prior day's file => 'no data', not an error."""
    from algo.data.providers.base import NotPublishedError

    sat = date(2026, 11, 7)
    with pytest.raises(NotPublishedError):
        list(P.parse("bhav", sat, RAW))  # RAW is dated 5 Nov
    holiday = NseBhavcopy(lambda u: RAW, nse({date(2026, 11, 6)}))
    with pytest.raises(NotPublishedError):
        list(holiday.parse("bhav", date(2026, 11, 6), RAW))


def test_file_dated_on_a_day_the_calendar_calls_closed_is_a_parse_error():
    """Data that claims to be from a 'closed' day is a surprise (special session? bad calendar?)
    and must be looked at by a human, not silently loaded or silently dropped."""
    closed = NseBhavcopy(lambda u: RAW, nse({D0}))
    with pytest.raises(ParseError, match="trading day"):
        list(closed.parse("bhav", D0, RAW))


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff\xfe",  # not utf-8
        b"SYMBOL,SERIES\nA,EQ\n",  # missing columns
        RAW.replace(b"05-Nov-2026", b"06-Nov-2026"),  # wrong date for partition
        RAW.replace(b"1324.00", b"abc"),  # bad number
        RAW.replace(b"05-Nov-2026", b"2026/11/05"),  # bad date format
    ],
)
def test_bad_input_raises_parse_error(raw):
    with pytest.raises(ParseError):
        list(P.parse("bhav", D0, raw))


def test_file_holding_an_earlier_day_means_not_published():
    """On holidays NSE serves the previous trading day's file: that is 'no data for this day',
    not corrupt data. A later date inside the file is still a genuine parse error."""
    from algo.data.providers.base import NotPublishedError

    stale = RAW.replace(b"05-Nov-2026", b"04-Nov-2026")
    with pytest.raises(NotPublishedError):
        list(P.parse("bhav", D0, stale))


def test_file_date_reports_the_single_date_a_file_really_holds():
    from algo.data.providers.nse_bhavcopy import file_date

    hdr = "SYMBOL, SERIES, DATE1, OPEN_PRICE\n"
    one = (hdr + "A, EQ, 04-Nov-2021, 1\nB, EQ, 04-Nov-2021, 2\n").encode()
    assert file_date(one) == date(2021, 11, 4)
    assert (
        file_date((hdr + "A, EQ, 03-Nov-2021, 1\nB, EQ, 04-Nov-2021, 2\n").encode()) is None
    )  # mixed
    assert file_date(hdr.encode()) is None  # no rows
    assert file_date(b"A,B\n1,2\n") is None  # no DATE1 column: a blank date cannot parse
    assert file_date(b"\xff\xfe") is None  # not text
    assert file_date((hdr + "A, EQ, notadate, 1\n").encode()) is None
