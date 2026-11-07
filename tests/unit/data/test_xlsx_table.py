import io
import zipfile

import pytest

from algo.data.providers import xlsx_table as xt
from algo.data.providers.base import ParseError

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def make(
    sheet_rows: str, shared: list[str] | None = None, sheet="xl/worksheets/sheet1.xml"
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(sheet, f"<worksheet {NS}><sheetData>{sheet_rows}</sheetData></worksheet>")
        if shared is not None:
            si = "".join(f"<si><t>{s}</t></si>" for s in shared)
            z.writestr("xl/sharedStrings.xml", f"<sst {NS}>{si}</sst>")
    return buf.getvalue()


def test_cells_are_read_exactly_as_stored_with_gaps_filled():
    raw = make(
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>108.10</v></c>'
        '<c r="C2" t="inlineStr"><is><t>EQ</t></is></c><c r="AA2"><v>7</v></c></row>'
        '<row r="3"/>',
        ["SYMBOL", "SERIES", "20MICRONS"],
    )
    rows = xt.xlsx_rows(raw)
    assert rows[0] == ["SYMBOL", "", "SERIES"]
    assert rows[1][:3] == ["20MICRONS", "108.10", "EQ"] and rows[1][26] == "7"
    assert len(rows[1]) == 27 and rows[2] == []  # trailing zeros kept: nothing became a float
    assert (
        xt.xlsx_to_csv(make('<row r="1"><c r="A1"><v>1.50</v></c><c r="B1"><v>x</v></c></row>'))
        == b"1.50,x\n"
    )


def test_detection_and_bad_inputs():
    assert xt.is_xlsx(make("")) and not xt.is_xlsx(b"SYMBOL,SERIES\n")
    for bad, msg in [
        (b"PK\x03\x04junk", "not a readable xlsx"),
        (make("", sheet="xl/worksheets/other.xml"), "no xl/worksheets/sheet1.xml"),
        (make('<row r="1"><c><v>1</v></c></row>'), "cell without a reference"),
        (make('<row r="1"><c r="A1" t="s"><v>9</v></c></row>', ["a"]), "bad shared string index"),
        (make('<row r="1"><c r="A1" t="s"><v>x</v></c></row>', ["a"]), "bad shared string index"),
    ]:
        with pytest.raises(ParseError, match=msg):
            xt.xlsx_rows(bad)


def test_an_oversized_part_is_refused(monkeypatch):
    monkeypatch.setattr(xt, "MAX_PART_BYTES", 10)
    with pytest.raises(ParseError, match="exceeds the 10 cap"):
        xt.xlsx_rows(make('<row r="1"><c r="A1"><v>1</v></c></row>'))


def test_a_sheet_without_shared_strings_is_fine():
    assert xt.xlsx_rows(make('<row r="1"><c r="A1"><v>5</v></c></row>')) == [["5"]]


def test_elements_in_a_row_that_are_not_cells_are_ignored():
    raw = make('<row r="1"><extLst/><c r="A1"><v>1</v></c></row><other/>')
    assert xt.xlsx_rows(raw) == [["1"]]


def test_a_binary_double_artefact_is_shortened_but_real_precision_is_kept():
    row = (
        '<row r="1"><c r="A1"><v>277.89999999999998</v></c><c r="B1"><v>108.10</v></c>'
        '<c r="C1"><v>-2254.8000000000002</v></c><c r="D1"><v>1687369</v></c>'
        '<c r="E1" t="n"><v>0.30000000000000004</v></c><c r="F1" t="str"><v>277.89999999999998</v></c>'
        '<c r="G1"><v>1.2345678901234567e-05</v></c></row>'
    )
    assert xt.xlsx_rows(make(row)) == [
        ["277.9", "108.10", "-2254.8", "1687369", "0.30000000000000004", "277.89999999999998",
         "1.2345678901234567e-05"]
    ]  # fmt: skip
    assert xt._number("12345678901234567") == "12345678901234567"  # repr would need an exponent
    assert xt._number("abcdefghijklmnopq") == "abcdefghijklmnopq"  # not a number: untouched
