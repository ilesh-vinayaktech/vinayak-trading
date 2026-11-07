from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.data.providers.base import ParseError
from algo.data.providers.nse_security_master import parse_security_master

RAW = (Path(__file__).parents[2] / "data/nse/EQUITY_L.csv").read_bytes()  # real excerpt


def test_parses_real_excerpt():
    secs = {s.symbol: s for s in parse_security_master(RAW)}
    r = secs["RELIANCE"]
    assert (r.name, r.series, r.isin, r.lot_size) == (
        "Reliance Industries Limited", "EQ", "INE002A01018", D(1)
    )  # fmt: skip
    assert r.listed_on == date(1995, 11, 29) and secs["AGSTRA"].series == "BZ"


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        b"SYMBOL,SERIES\nA,EQ\n",
        RAW.replace(b"29-NOV-1995", b"never"),
        RAW.replace(b",1,INE002", b",x,INE002"),
    ],
)
def test_bad_input(raw):
    with pytest.raises(ParseError):
        parse_security_master(raw)
