from datetime import date
from pathlib import Path

import pytest

from algo.data.providers.base import ParseError
from algo.data.providers.nse_symbol_changes import parse_index_list, parse_symbol_changes

DATA = Path(__file__).parents[2] / "data/nse"
CHG = (DATA / "symbolchange_sample.csv").read_bytes()  # real NSE rows
IDX = (DATA / "ind_nifty200list_sample.csv").read_bytes()  # real NSE rows


def test_real_symbol_changes():
    ch = {(c.old, c.new): c.effective for c in parse_symbol_changes(CHG)}
    assert ch[("ZOMATO", "ETERNAL")] == date(2025, 4, 9)
    assert ch[("TELCO", "TATAMOTORS")] == date(2003, 12, 26)
    assert ch[("TATAMOTORS", "TMPV")] == date(2025, 10, 24)
    assert ch[("RDAXEDG", "NDAXEDG")] == date(2019, 10, 30)  # leading space in name column ok


def test_real_index_list():
    m = {x.symbol: x for x in parse_index_list(IDX)}
    assert set(m) == {"ADANIENT", "BAJFINANCE", "ETERNAL", "RELIANCE", "TCS", "TMPV"}
    assert (m["TMPV"].isin, m["RELIANCE"].industry) == (
        "INE155A01022",
        "Oil Gas & Consumable Fuels",
    )


@pytest.mark.parametrize("raw", [b"\xff", b"A,B\n1,2\n", CHG.replace(b"09-APR-2025", b"soon")])
def test_symbol_changes_bad_input(raw):
    with pytest.raises(ParseError):
        parse_symbol_changes(raw)


def test_index_list_bad_input():
    with pytest.raises(ParseError):
        parse_index_list(b"Symbol\nX\n")
