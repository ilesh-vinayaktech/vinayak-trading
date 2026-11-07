import json
from datetime import date
from decimal import Decimal as D

import pytest

from algo.data.providers import niftyindices_price as px
from algo.data.providers.niftyindices_tri import TriError, windows


def row(d, close, **kw):
    return {"RequestNumber": "His1", "INDEX_NAME": "Nifty 200", "HistoricalDate": d,
            "OPEN": "-", "HIGH": "-", "LOW": "-", "CLOSE": close, **kw}  # fmt: skip


def raw(*rows):
    return json.dumps(list(rows)).encode()


def test_close_is_the_level_and_ohlc_stay_in_the_raw_response():
    obs = px.parse_response(
        raw(row("30 Oct 2026", "13183.95", OPEN="13180.9"), row("01 Jan 2004", "1000.00"))
    )
    assert [(o.day, o.level, o.net_level) for o in obs] == [
        (date(2026, 10, 30), D("13183.95"), None),
        (date(2004, 1, 1), D("1000.00"), None),
    ]


def test_the_request_number_and_name_casing_do_not_change_the_data_hash():
    a = px.parse_response(raw(row("30 Oct 2026", "1.5"), row("29 Oct 2026", "1.4")))
    b = px.parse_response(raw(row("29 Oct 2026", "1.4", RequestNumber="His2", INDEX_NAME="NIFTY 200"),
                              row("30 Oct 2026", "1.5")))  # fmt: skip
    assert px.normalized_hash(a) == px.normalized_hash(b)


@pytest.mark.parametrize(
    ("bad", "msg"),
    [
        (b"<html>", "^not JSON: "),
        (b'{"a": 1}', "^expected a JSON array$"),
        (raw({"CLOSE": "1"}), "^row without HistoricalDate / CLOSE: "),
        (raw("x"), "^row without HistoricalDate / CLOSE: 'x'$"),
        (raw(row("30 Oct 2026", "-")), "^malformed CLOSE '-'$"),
        (raw(row("31 Feb 2026", "1")), "impossible date"),
    ],
)  # fmt: skip
def test_a_malformed_response_is_refused_whole(bad, msg):
    with pytest.raises(TriError, match=msg):
        px.parse_response(bad)


def test_a_row_with_exactly_the_two_needed_fields_is_accepted():
    obs = px.parse_response(
        json.dumps([{"HistoricalDate": "02 Jan 2004", "CLOSE": "1010.5"}]).encode()
    )
    assert [(o.day, o.level) for o in obs] == [(date(2004, 1, 2), D("1010.5"))]


def test_the_endpoint_is_the_price_one_and_windows_are_shared():
    assert px.ENDPOINT.endswith("/getHistoricaldatatabletoString")
    assert px.windows(date(2004, 1, 1), date(2005, 1, 5)) == windows(
        date(2004, 1, 1), date(2005, 1, 5)
    )
    assert b"'indexName':'Nifty 200'" in px.request_body(
        "Nifty 200", date(2004, 1, 1), date(2004, 12, 31)
    )
    assert px.MAX_DAYS == 365
