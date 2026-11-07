import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.data.providers.niftyindices_tri import (
    Observation,
    TriError,
    fmt_date,
    normalized_hash,
    parse_date,
    parse_response,
    request_body,
    windows,
)  # fmt: skip

FIX = Path(__file__).parents[2] / "data/tri/nifty200_tri_2021-10-25_2021-11-02.json"


def test_windows_are_consecutive_non_overlapping_and_at_most_365_days():
    w = windows(date(2004, 1, 1), date(2006, 6, 30))
    assert w[0] == (date(2004, 1, 1), date(2004, 12, 30)) and w[1][0] == date(2004, 12, 31)
    assert all((b - a).days + 1 <= 365 for a, b in w)
    assert all(
        w[i][1] + (date(2004, 1, 2) - date(2004, 1, 1)) == w[i + 1][0] for i in range(len(w) - 1)
    )
    assert w[-1][1] == date(2006, 6, 30) and w[0][0] == date(2004, 1, 1)
    assert windows(date(2020, 1, 1), date(2020, 1, 1)) == [(date(2020, 1, 1), date(2020, 1, 1))]
    assert windows(date(2020, 1, 1), date(2020, 12, 30)) == [
        (date(2020, 1, 1), date(2020, 12, 30))
    ]  # 365
    assert len(windows(date(2020, 1, 1), date(2020, 12, 31))) == 2  # 366 days need two windows
    with pytest.raises(ValueError, match="end before start"):
        windows(date(2020, 1, 2), date(2020, 1, 1))


def test_the_request_matches_the_sites_own_format():
    assert (
        fmt_date(date(2025, 10, 31)) == "31-Oct-2025"
        and fmt_date(date(2004, 1, 1)) == "01-Jan-2004"
    )
    body = json.loads(request_body("Nifty 200", date(2025, 10, 31), date(2026, 10, 30)))
    assert body == {
        "cinfo": "{'name':'NIFTY 200','startDate':'31-Oct-2025','endDate':'30-Oct-2026','indexName':'Nifty 200'}"
    }


def test_a_real_response_parses_to_observations_with_two_decimal_levels():
    obs = parse_response(FIX.read_bytes())
    assert [o.day for o in obs] == sorted((o.day for o in obs), reverse=True) or len(obs) == 7
    by = {o.day: o for o in obs}
    assert len(obs) == 7 and by[date(2021, 10, 29)] == Observation(
        date(2021, 10, 29), D("11934.47"), None
    )
    assert by[date(2021, 11, 2)].level == D("12105.52")


def test_dates_and_levels_are_strict():
    assert parse_date("30 Oct 2026") == date(2026, 10, 30) and parse_date("1 Jan 2004") == date(
        2004, 1, 1
    )
    for bad in ("2026-10-30", "30 October 2026", "30 Foo 2026", "31 Feb 2026", ""):
        with pytest.raises(TriError, match="date"):
            parse_date(bad)


@pytest.mark.parametrize(
    ("raw", "msg"),
    [
        (b"<html>", "not JSON"),
        (b'{"a": 1}', "expected a JSON array"),
        (b'[{"Date": "30 Oct 2026"}]', "row without Date / TotalReturnsIndex"),
        (b'["x"]', "row without Date / TotalReturnsIndex"),
        (b'[{"Date": "30 Oct 2026", "TotalReturnsIndex": "abc"}]', "malformed level"),
        (b'[{"Date": "30 Oct 2026", "TotalReturnsIndex": 12.5}]', "malformed level"),
        (b'[{"Date": "30 Oct 2026", "TotalReturnsIndex": "-5.00"}]', "malformed level"),
        (b'[{"Date": "bad", "TotalReturnsIndex": "5.00"}]', "malformed date"),
        (
            b'[{"Date": "30 Oct 2026", "TotalReturnsIndex": "5.00", "NTR_Value": "x"}]',
            "malformed NTR_Value",
        ),
    ],
)
def test_one_bad_row_refuses_the_whole_response(raw, msg):
    with pytest.raises(TriError, match=msg):
        parse_response(raw)


def test_a_net_value_is_read_when_present_and_dash_means_none():
    raw = b'[{"Date": "30 Oct 2026", "TotalReturnsIndex": "100.00", "NTR_Value": "99.50"},' \
          b'{"Date": "29 Oct 2026", "TotalReturnsIndex": "99.00", "NTR_Value": "-"}]'  # fmt: skip
    a, b = parse_response(raw)
    assert a.net_level == D("99.50") and b.net_level is None


def test_the_normalized_hash_identifies_the_data_not_the_response():
    rows = lambda rn, name, order: json.dumps(  # noqa: E731
        [{"RequestNumber": rn, "Index Name": name, "Date": d, "TotalReturnsIndex": v, "NTR_Value": "-"}
         for d, v in order]).encode()  # fmt: skip
    pairs = [("30 Oct 2026", "100.00"), ("29 Oct 2026", "99.00")]
    h1 = normalized_hash(parse_response(rows("TRI1", "Nifty 200", pairs)))
    h2 = normalized_hash(parse_response(rows("TRI2", "NIFTY 200", list(reversed(pairs)))))
    assert h1 == h2  # request number, name casing and order do not matter
    changed = normalized_hash(
        parse_response(rows("TRI1", "Nifty 200", [("30 Oct 2026", "100.01"), pairs[1]]))
    )
    assert changed != h1 and normalized_hash([]) != h1
