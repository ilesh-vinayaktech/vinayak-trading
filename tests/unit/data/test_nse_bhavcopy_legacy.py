import io
import zipfile
from datetime import date
from decimal import Decimal as D

import pytest

from algo.data.providers import nse_bhavcopy_legacy as lg
from algo.data.providers.base import ParseError

HEAD = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,"


def zipped(*lines, head=HEAD, names=("cm.csv",)):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "\n".join([head, *lines]) + "\n")
    return buf.getvalue()


ROW1 = "20MICRONS,EQ,36.3,42.8,35.5,36.05,35.75,35.85,24481,890258.7,28-FEB-2015,258,INE144J01027,"
ROW2 = "ABB,EQ,1,2,1,1.5,1.5,1.25,1,1,28-FEB-2015,1,INE117A01022,"


def test_url_uses_the_archive_layout_with_an_upper_case_month():
    assert lg.url(date(2015, 2, 28)).endswith(
        "/content/historical/EQUITIES/2015/FEB/cm28FEB2015bhav.csv.zip"
    )
    assert lg.url(date(2003, 11, 5)).endswith("/2003/NOV/cm05NOV2003bhav.csv.zip")


def test_parse_reads_the_date_the_file_holds_and_its_closes():
    b = lg.parse(zipped(ROW1, ROW2))
    assert b.days == frozenset({date(2015, 2, 28)}) and b.rows == 2
    assert b.close[("20MICRONS", "EQ")] == D("36.05") and b.prev_close[("ABB", "EQ")] == D("1.25")


def test_a_file_that_mixes_dates_reports_all_of_them():
    other = ROW2.replace("28-FEB-2015", "27-Feb-2015")
    assert lg.parse(zipped(ROW1, other)).days == frozenset({date(2015, 2, 28), date(2015, 2, 27)})


@pytest.mark.parametrize(
    ("raw", "msg"),
    [
        (b"not a zip", "not a readable"),
        (zipped(ROW1, names=("a.csv", "b.csv")), "expected one file"),
        (zipped(ROW1, head="SYMBOL,SERIES"), "missing columns"),
        (zipped(), "no rows"),
        (zipped(ROW1.replace("28-FEB-2015", "28/02/2015")), "malformed TIMESTAMP"),
        (zipped(ROW1.replace("28-FEB-2015", "31-FEB-2015")), "impossible TIMESTAMP"),
        (zipped(ROW1.replace("28-FEB-2015", "28-XXX-2015")), "malformed TIMESTAMP"),
        (zipped(ROW1.replace("36.05,35.75", "n/a,35.75")), "non-numeric price"),
    ],
)
def test_bad_archives_are_refused(raw, msg):
    with pytest.raises(ParseError, match=msg):
        lg.parse(raw)


def test_oversized_members_are_refused(monkeypatch):
    monkeypatch.setattr(lg, "MAX_BYTES", 10)
    with pytest.raises(ParseError, match="too large"):
        lg.parse(zipped(ROW1))


def test_chain_counts_symbols_whose_prev_close_equals_the_earlier_close():
    earlier = {("A", "EQ"): D("10"), ("B", "EQ"): D("20"), ("C", "EQ"): D("5")}
    later = {("A", "EQ"): D("10.0"), ("B", "EQ"): D("21"), ("D", "EQ"): D("1")}
    assert lg.chain(earlier, later) == (2, 1)
    assert lg.chain({}, later) == (0, 0)
