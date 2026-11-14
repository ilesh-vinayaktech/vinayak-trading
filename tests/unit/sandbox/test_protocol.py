from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.data.reader import AdjBar
from algo.sandbox.protocol import Bar, ProtocolError, dumps, loads

T = datetime(2026, 11, 16, 3, 45, tzinfo=UTC)


def test_values_travel_without_being_rounded_or_reinterpreted():
    msg = {
        "d": D("1234.5678901234567890123"),
        "t": T,
        "day": date(2026, 11, 16),
        "n": 7,
        "s": "x",
        "none": None,
        "l": [D(1), D("2.50")],
    }
    back = loads(dumps(msg))
    assert back == msg and isinstance(back["d"], D) and back["d"] == D("1234.5678901234567890123")
    assert back["t"] == T and back["t"].tzinfo is not None and back["day"] == date(2026, 11, 16)


def test_the_same_message_always_encodes_to_the_same_bytes():
    a = dumps({"b": 1, "a": D("1.0")})
    assert a == dumps({"a": D("1.0"), "b": 1}) == '{"a":{"$d":"1.0"},"b":1}'
    assert D("1.0") == D("1.00") and dumps({"x": D("1.0")}) != dumps(
        {"x": D("1.00")}
    )  # the text is kept, so replays match


def test_a_platform_bar_arrives_as_a_bar_with_the_same_fields():
    bar = AdjBar(T, D(10), D(12), D(9), D(11), D(1000), D(1), 7)
    (got,) = loads(dumps({"bars": [bar]}))["bars"]
    assert isinstance(got, Bar) and (
        got.ts,
        got.open,
        got.close,
        got.volume,
        got.factor,
        got.owner,
    ) == (T, D(10), D(11), D(1000), D(1), 7)
    assert (
        got == loads(dumps({"bars": [bar]}))["bars"][0]
        and hash(got) == hash(got)
        and "close=11" in repr(got)
    )
    none_owner = AdjBar(T, D(1), D(1), D(1), D(1), D(1), D(1), None)
    assert loads(dumps({"b": none_owner}))["b"].owner is None
    assert got != "x"


def test_things_that_are_not_data_are_refused():
    with pytest.raises(ProtocolError, match="cannot send"):
        dumps({"x": object()})
    with pytest.raises(ProtocolError):
        dumps({"x": float("nan")})
    with pytest.raises(ProtocolError, match="not JSON"):
        loads("{nope")
    with pytest.raises(ProtocolError, match="object"):
        loads("[1]")
    assert loads('{"a":{"x":1,"y":2}}') == {
        "a": {"x": 1, "y": 2}
    }  # a dict with other keys is left alone
