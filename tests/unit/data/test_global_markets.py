import json
from datetime import UTC, date, datetime, timedelta

import pytest

from algo.data.global_markets import (
    GIFT_AT,
    gift_reading,
    last_session_return,
    parse_yahoo,
    yahoo_url,
)

D = date(2026, 11, 16)


def chart(stamps, closes, offset=-18000):
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"gmtoffset": offset},
                        "timestamp": stamps,
                        "indicators": {"quote": [{"close": closes}]},
                    }
                ]
            }
        }
    ).encode()


def test_yahoo_closes_take_the_markets_own_date_and_skip_sessions_without_a_close():
    t = int(datetime(2026, 11, 16, 14, 30, tzinfo=UTC).timestamp())  # 09:30 New York
    got = parse_yahoo(chart([t, t + 86400, t + 2 * 86400], [7300.5, None, 7350.0]))
    assert got == [(date(2026, 11, 16), 7300.5), (date(2026, 11, 18), 7350.0)]


def test_a_payload_that_is_not_a_chart_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="not understood"):
        parse_yahoo(b'{"chart": {"result": null}}')
    with pytest.raises(ValueError, match="not understood"):
        parse_yahoo(b"<html>")


def test_the_url_asks_for_daily_candles_over_the_window():
    u = yahoo_url("^GSPC", D, D + timedelta(days=5))
    assert "%5EGSPC" in u and "interval=1d" in u and "period1=" in u


def test_the_gift_reading_is_the_candle_that_opens_at_0845_ist():
    ist = lambda h, m: datetime(2026, 11, 18, h, m, tzinfo=UTC) - timedelta(hours=5, minutes=30)  # noqa: E731
    candles = [
        (ist(8, 44), 25000.0),
        (ist(*divmod(GIFT_AT.hour * 60 + GIFT_AT.minute, 60)), 25100.0),
        (ist(8, 46), 25200.0),
    ]
    assert gift_reading(candles) == [(date(2026, 11, 18), 25100.0)]


def test_the_overnight_return_is_the_last_session_before_the_day_against_the_one_before():
    rows = [(date(2026, 11, 12), 100.0), (date(2026, 11, 13), 101.0), (date(2026, 11, 16), 103.02)]
    assert (
        round(last_session_return(rows, date(2026, 11, 17)), 4) == 2.0
    )  # Tuesday morning: Monday's session
    assert (
        round(last_session_return(rows, date(2026, 11, 16)), 4) == 1.0
    )  # Monday morning: Friday's session, Monday's own is later
    assert last_session_return(rows[:1], date(2026, 11, 17)) is None
