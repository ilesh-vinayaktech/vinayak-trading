"""AMFI's half-yearly market-cap ranking -> large / mid / small / micro by rank, known from a conservative date."""

import io
import zipfile
from datetime import date
from decimal import Decimal as D

import pytest

from algo.data.amfi_caps import AmfiError, effective_from, parse_list, segment_of

HEADER = [
    "Sr. No.", "Company name", "ISIN", "BSE Symbol", "BSE 6 month Avg Total Market Cap in (Rs. Crs.)", "NSE Symbol",
    "NSE 6 month Avg Total Market Cap (Rs. Crs.)", "MSEI Symbol", "MSEI 6 month Avg Total Market Cap in (Rs Crs.)",
    "Average of All Exchanges (Rs. Cr.)", "Categorization as per SEBI Circular dated Oct 6, 2017",
]  # fmt: skip
TITLE = "Average Market Capitalization of listed companies during the six months ended 30 June 2026"


def xlsx(rows) -> bytes:
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    col = lambda j: "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[j]  # noqa: E731
    body = "".join(
        f'<row r="{i}">' + "".join(f'<c r="{col(j)}{i}" t="inlineStr"><is><t>{v}</t></is></c>' for j, v in enumerate(r)) + "</row>"
        for i, r in enumerate(rows, 1)
    )  # fmt: skip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{body}</sheetData></worksheet>"
        )
    return buf.getvalue()


def company(rank, isin=None, nse=None, cap=None, category=None):
    cat = (
        category
        if category is not None
        else ("Large Cap" if rank <= 100 else "Mid Cap" if rank <= 250 else "Small Cap")
    )
    return [str(rank), f"Company {rank} Ltd", isin or f"INE{rank:09d}", f"B{rank}", "1", nse if nse is not None else f"S{rank}",
            "1", "-", "", cap or str(100000 - rank), cat]  # fmt: skip


def a_list(n=260, title=TITLE, **over):
    rows = [company(r) for r in range(1, n + 1)]
    for rank, row in over.items():
        rows[int(rank[1:]) - 1] = row
    return xlsx([[title] + [""] * 10, HEADER, *rows])


def test_a_list_gives_the_period_and_each_companys_rank_isin_nse_symbol_and_average_cap():
    got = parse_list(a_list())
    assert got.period_end == date(2026, 6, 30) and len(got.rows) == 260
    first = got.rows[0]
    assert (first.rank, first.isin, first.nse_symbol, first.name, first.avg_cap) == (
        1,
        "INE000000001",
        "S1",
        "Company 1 Ltd",
        D(99999),
    )


def test_december_lists_and_numbers_in_exponent_form_are_read():
    got = parse_list(
        a_list(
            title=TITLE.replace("30 June 2026", "31 December 2021"),
            r5=company(5, cap="2.4500000000000001E-2"),
        )
    )
    assert got.period_end == date(2021, 12, 31) and got.rows[4].avg_cap == D("0.024500000000000001")


def test_a_company_without_an_nse_listing_keeps_no_symbol():
    got = parse_list(a_list(n=600, r600=company(600, nse="-")))
    assert got.rows[-1].nse_symbol is None and got.rows[-1].rank == 600


def test_numbered_rows_with_nothing_else_are_not_companies():
    rows = [company(r) for r in range(1, 261)] + [["261"] + [""] * 10, ["262"] + [""] * 10]
    assert len(parse_list(xlsx([[TITLE], HEADER, *rows])).rows) == 260


def test_the_segment_follows_the_rank_the_way_sebi_defines_it_with_micro_beyond_500():
    assert [segment_of(r) for r in (1, 100, 101, 250, 251, 500, 501, 5000)] == [
        "large", "large", "mid", "mid", "small", "small", "micro", "micro",
    ]  # fmt: skip


def test_a_list_is_relied_on_only_from_the_first_day_of_the_second_month_after_its_period():
    assert effective_from(date(2026, 6, 30)) == date(2026, 8, 1)
    assert effective_from(date(2025, 12, 31)) == date(2026, 2, 1)


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        (b"not a spreadsheet", "not a spreadsheet"),
        (xlsx([["Some other report"], HEADER, company(1)]), "period"),
        (xlsx([[TITLE], ["Sr. No.", "Company name", "Price"], company(1)]), "columns"),
        (a_list(r2=company(3)), "ranks"),
        (a_list(r100=company(100, category="Mid Cap")), "rank 100"),
        (a_list(r7=company(7, isin="BAD")), "ISIN"),
        (xlsx([[TITLE], HEADER]), "no companies"),
        (a_list(r9=company(9, cap="n/a")), "market cap"),
        (a_list(r255=company(255, category="")), "rank 255"),
        (
            a_list(title="Average Market Capitalization during the six months ended 30 Junly 2026"),
            "period",
        ),
    ],
)
def test_a_list_that_does_not_read_exactly_as_expected_is_refused(raw, why):
    with pytest.raises(AmfiError, match=why):
        parse_list(raw)


def test_notes_and_blank_lines_around_the_table_are_skipped():
    raw = xlsx([[TITLE], HEADER, company(1), [], ["Note: market cap in Rs crore"], company(2)])
    assert [r.rank for r in parse_list(raw).rows] == [1, 2]


def test_an_old_bse_only_company_without_an_isin_keeps_its_rank_but_no_isin():
    got = parse_list(a_list(n=300, r290=company(290, isin="NA", nse="")))
    assert (got.rows[289].isin, got.rows[289].nse_symbol, got.rows[290 - 1].rank) == (
        None,
        None,
        290,
    )


def test_companies_with_the_same_cap_share_a_rank_and_the_next_one_resumes_at_its_position():
    rows = [company(r) for r in range(1, 261)] + [
        company(261),
        company(261),
        company(261),
        company(264),
    ]
    got = parse_list(xlsx([[TITLE], HEADER, *rows]))
    assert [r.rank for r in got.rows[-4:]] == [261, 261, 261, 264]
