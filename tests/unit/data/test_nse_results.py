from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.data.providers.nse_results import (
    XbrlError,
    parse_integrated_listing,
    parse_listing,
    parse_xbrl,
)

DATA = Path(__file__).parents[2] / "data/nse"


def fx(name: str) -> bytes:
    return (DATA / name).read_bytes()


def test_the_listing_gives_every_quarterly_filing_with_its_exact_broadcast_time_in_utc():
    fs = parse_listing(fx("results_listing_RELIANCE.json"))
    assert len(fs) == 4
    cons = next(f for f in fs if f.period_end == date(2024, 12, 31) and f.basis == "CONSOLIDATED")
    assert (cons.symbol, cons.isin, cons.period_start, cons.seq_number) == (
        "RELIANCE",
        "INE002A01018",
        date(2024, 10, 1),
        "1189821",
    )
    assert cons.filed_at == datetime(2025, 1, 16, 14, 45, 20, tzinfo=UTC)  # 20:15:20 IST
    assert (cons.audited, cons.bank, cons.cumulative) == (False, False, False)
    assert cons.xbrl_url is not None and cons.xbrl_url.endswith("_1348248_16012025081520.xml")
    stand = next(f for f in fs if f.period_end == date(2024, 12, 31) and f.basis == "STANDALONE")
    assert (
        stand.filed_at == datetime(2025, 1, 16, 14, 50, 21, tzinfo=UTC)
        and stand.seq_number != cons.seq_number
    )


def test_an_old_format_filing_has_a_detail_page_but_no_xbrl():
    old = [
        f
        for f in parse_listing(fx("results_listing_RELIANCE.json"))
        if f.period_end == date(2017, 12, 31)
    ]
    assert len(old) == 2 and all(f.xbrl_url is None for f in old)
    assert all(f.detail_url and f.detail_url.endswith(".html") for f in old)


def test_a_bank_listing_carries_the_bank_flag():
    (f,) = parse_listing(fx("results_listing_HDFCBANK.json"))
    assert f.bank is True and f.basis == "CONSOLIDATED"


def test_a_listing_that_is_not_a_list_of_filings_is_refused():
    with pytest.raises(XbrlError, match="not a results listing"):
        parse_listing(b'{"error": "blocked"}')
    with pytest.raises(XbrlError, match="not a results listing"):
        parse_listing(b"<html>Access Denied</html>")


def test_a_non_bank_statement_gives_the_quarter_and_the_year_to_date_in_rupees():
    s = parse_xbrl(fx("results_xbrl_RELIANCE_cons.xml"))
    assert (s.period_start, s.period_end, s.basis, s.audited, s.rounding) == (
        date(2024, 10, 1),
        date(2024, 12, 31),
        "CONSOLIDATED",
        False,
        "Crores",
    )
    q = s.quarter
    assert q["revenue"] == D("2438650000000.00") and q["total_income"] == D("2480790000000.00")
    assert q["expenses"] == D("2194360000000.00") and q["finance_costs"] == D("61790000000.00")
    assert q["depreciation"] == D("131810000000.00") and q["other_income"] == D("42140000000.00")
    assert (
        q["pbt"] == D("286430000000.00")
        and q["tax"] == D("68390000000.00")
        and q["pat"] == D("219300000000.00")
    )
    assert (
        q["pat_owners"] == D("185400000000.00")
        and q["eps_basic"] == D("13.70")
        and q["eps_diluted"] == D("13.70")
    )
    assert "interest_earned" not in q  # a bank-only line
    assert (
        s.ytd["revenue"] > q["revenue"] and s.ytd["pat"] > q["pat"]
    )  # nine months exceed one quarter


def test_a_bank_statement_maps_its_own_taxonomy_onto_the_same_metrics():
    s = parse_xbrl(fx("results_xbrl_HDFCBANK_cons.xml"))
    q = s.quarter
    assert (s.basis, s.period_end) == ("CONSOLIDATED", date(2024, 12, 31))
    assert (
        q["revenue"] == D("1121939400000.00") == q["total_income"]
    )  # a bank's revenue is its total income
    assert q["interest_earned"] == D("850401700000.00") and q["interest_expended"] == D(
        "469142800000.00"
    )
    assert q["operating_profit"] == D("279301600000.00") and q["provisions"] == D("39572900000.00")
    assert (
        q["expenses"] == D("842637800000.00")
        and q["pbt"] == D("239728700000.00")
        and q["tax"] == D("56327600000.00")
    )
    assert q["pat"] == D("183401100000.00") and q["pat_owners"] == D("176566100000.00")
    assert q["eps_basic"] == D("23.11") and q["eps_diluted"] == D("23.00")


def XML(body: str, ctx: str = "") -> bytes:
    return (
        '<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"'
        ' xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2020-03-31/in-bse-fin"'
        ' xmlns:xbrldi="http://xbrl.org/2006/xbrldi">'
        '<xbrli:context id="OneD"><xbrli:entity/><xbrli:period><xbrli:startDate>2024-10-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>'
        '<xbrli:context id="FourD"><xbrli:entity/><xbrli:period><xbrli:startDate>2024-04-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>'
        f"{ctx}{body}</xbrli:xbrl>"
    ).encode()


BASE = (
    '<in-bse-fin:DateOfStartOfReportingPeriod contextRef="OneD">2024-10-01</in-bse-fin:DateOfStartOfReportingPeriod>'
    '<in-bse-fin:DateOfEndOfReportingPeriod contextRef="OneD">2024-12-31</in-bse-fin:DateOfEndOfReportingPeriod>'
    '<in-bse-fin:NatureOfReportStandaloneConsolidated contextRef="OneD">Standalone</in-bse-fin:NatureOfReportStandaloneConsolidated>'
    '<in-bse-fin:WhetherResultsAreAuditedOrUnaudited contextRef="OneD">Audited</in-bse-fin:WhetherResultsAreAuditedOrUnaudited>'
    '<in-bse-fin:LevelOfRoundingUsedInFinancialStatements contextRef="OneD">Lakhs</in-bse-fin:LevelOfRoundingUsedInFinancialStatements>'
)


def test_values_from_segment_or_other_dimensional_contexts_never_become_company_totals():
    seg = '<xbrli:context id="OneSeg"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="d">m</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2024-10-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>'
    body = (
        BASE
        + '<in-bse-fin:RevenueFromOperations contextRef="OneSeg">1</in-bse-fin:RevenueFromOperations><in-bse-fin:RevenueFromOperations contextRef="OneD">999.50</in-bse-fin:RevenueFromOperations>'
    )
    s = parse_xbrl(XML(body, seg))
    assert (
        s.quarter["revenue"] == D("999.50")
        and s.audited is True
        and s.basis == "STANDALONE"
        and s.ytd == {}
    )


def test_a_missing_line_is_absent_not_zero_and_bad_numbers_are_refused():
    s = parse_xbrl(
        XML(
            BASE
            + '<in-bse-fin:ProfitLossForPeriod contextRef="OneD">-12.5</in-bse-fin:ProfitLossForPeriod>'
        )
    )
    assert s.quarter == {
        "pat": D("-12.5")
    }  # a loss is a negative number; lines not reported are simply missing
    with pytest.raises(XbrlError, match="not a number"):
        parse_xbrl(
            XML(
                BASE
                + '<in-bse-fin:ProfitLossForPeriod contextRef="OneD">n/a</in-bse-fin:ProfitLossForPeriod>'
            )
        )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"<html>not xbrl</html>", "not an XBRL"),
        (b"\x00\x01", "not an XBRL"),
        (
            XML(
                '<in-bse-fin:ProfitLossForPeriod contextRef="OneD">1</in-bse-fin:ProfitLossForPeriod>'
            ),
            "reporting period",
        ),
        (XML(BASE.replace("Standalone", "Neither")), "standalone or consolidated"),
        (
            XML(
                BASE.replace(
                    "2024-12-31</in-bse-fin:DateOfEndOfReportingPeriod>",
                    "2025-12-31</in-bse-fin:DateOfEndOfReportingPeriod>",
                )
            ),
            "contain no quarter",
        ),
    ],
)
def test_statements_that_cannot_be_read_unambiguously_are_refused(raw, message):
    with pytest.raises(XbrlError, match=message):
        parse_xbrl(raw)


def test_dtd_and_entity_declarations_are_refused_before_parsing():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">&a;</xbrli:xbrl>'
    with pytest.raises(XbrlError, match="DTD/entity declarations refused"):
        parse_xbrl(bomb)


def test_a_filing_with_no_broadcast_time_is_listed_with_filed_at_none_not_guessed():
    import json

    row = json.loads(fx("results_listing_RELIANCE.json"))[0]
    row["broadCastDate"], row["exchdisstime"] = None, None
    (f,) = parse_listing(json.dumps([row]).encode())
    assert f.filed_at is None and f.disseminated_at is None and f.symbol == "RELIANCE"


def test_older_statements_that_use_but_never_define_the_standard_contexts_are_read_too():
    s = parse_xbrl(fx("results_xbrl_RELIANCE_cons_2021.xml"))
    assert (s.period_start, s.period_end, s.basis, s.audited) == (
        date(2020, 10, 1),
        date(2020, 12, 31),
        "CONSOLIDATED",
        False,
    )
    q = s.quarter
    assert (
        q["revenue"] == D("1239970000000.00")
        and q["pbt"] == D("149070000000.00")
        and q["tax"] == D("880000000.00")
    )
    assert (
        q["pat"] == D("148940000000.00")
        and q["pat_owners"] == D("131010000000.00")
        and q["eps_basic"] == D("20.33")
    )
    assert s.ytd["revenue"] > q["revenue"]  # nine months, from the FourD facts


def test_older_bank_statements_that_give_only_the_period_end_derive_the_quarter_from_the_convention():
    s = parse_xbrl(fx("results_xbrl_HDFCBANK_cons_2021.xml"))
    assert (s.period_start, s.period_end, s.basis) == (
        date(2020, 10, 1),
        date(2020, 12, 31),
        "CONSOLIDATED",
    )
    q = s.quarter
    assert q["revenue"] == D("398387300000.00") and q["interest_earned"] == D("318516000000.00")
    assert (
        q["pbt"] == D("118132000000.00")
        and q["pat"] == D("87601900000.00")
        and q["pat_owners"] == D("87693300000.00")
    )
    assert s.ytd["revenue"] > q["revenue"]  # the year to date starts at the financial year start


def _no_start(end: str, ctx: str = "OneD", extra: str = "") -> bytes:
    return XML(
        f'<in-bse-fin:DateOfEndOfReportingPeriod contextRef="{ctx}">{end}</in-bse-fin:DateOfEndOfReportingPeriod>'
        '<in-bse-fin:NatureOfReportStandaloneConsolidated contextRef="OneD">Standalone</in-bse-fin:NatureOfReportStandaloneConsolidated>'
        f'<in-bse-fin:ProfitLossForPeriod contextRef="{ctx}">5</in-bse-fin:ProfitLossForPeriod>{extra}'
    )


def test_the_period_start_is_derived_only_from_the_quarter_context_and_a_calendar_quarter_end():
    s = parse_xbrl(_no_start("2024-03-31"))
    assert (s.period_start, s.period_end) == (
        date(2024, 1, 1),
        date(2024, 3, 31),
    ) and s.quarter == {"pat": D(5)}
    assert parse_xbrl(_no_start("2024-12-31")).period_start == date(2024, 10, 1)
    for bad in ("2024-04-30", "2024-03-30"):  # not a calendar quarter end
        with pytest.raises(XbrlError, match="reporting period"):
            parse_xbrl(_no_start(bad))
    with pytest.raises(XbrlError, match="reporting period"):
        parse_xbrl(
            _no_start("2024-03-31", ctx="TwoD")
        )  # not the current-quarter context by convention


def test_the_integrated_filing_listing_gives_basis_time_and_a_seq_number_that_cannot_clash_with_the_old_feed():
    fs = parse_integrated_listing(fx("integrated_listing_TCS.json"))
    assert len(fs) == 3
    cons = next(f for f in fs if f.symbol == "TCS" and f.basis == "CONSOLIDATED")
    assert (cons.period_end, cons.period_start, cons.seq_number) == (
        date(2026, 9, 30),
        date(2026, 7, 1),
        "IF200121",
    )
    assert cons.filed_at == datetime(2026, 10, 8, 16, 37, 33, tzinfo=UTC)  # 22:07:33 IST
    assert (cons.audited, cons.cumulative, cons.isin, cons.bank) == (True, False, "", False)
    assert cons.xbrl_url is not None and cons.xbrl_url.endswith("_WEB.xml")


def test_a_revision_is_known_from_its_revision_time_when_it_has_no_broadcast_time():
    rev = next(
        f
        for f in parse_integrated_listing(fx("integrated_listing_TCS.json"))
        if f.symbol == "PAGEIND"
    )
    assert rev.filed_at == datetime(2026, 11, 12, 11, 39, 9, tzinfo=UTC)  # 17:09:09 IST


def test_integrated_listing_refuses_anything_that_is_not_the_listing():
    with pytest.raises(XbrlError):
        parse_integrated_listing(b'{"nodata": 1}')


def test_the_integrated_xbrl_reads_with_the_same_parser_and_reports_isin_and_rounding():
    s = parse_xbrl(fx("integrated_xbrl_TCS_cons_2026q2.xml"))
    assert (s.period_start, s.period_end, s.basis, s.audited) == (
        date(2026, 7, 1),
        date(2026, 9, 30),
        "CONSOLIDATED",
        True,
    )
    assert s.quarter["revenue"] == D("731880000000") and s.ytd["pat"] == D("273540000000")
    assert (s.isin, s.rounding) == ("INE467B01029", "Crores")


def test_every_company_level_number_in_the_filing_is_kept_by_the_scope_it_was_reported_in():
    s = parse_xbrl(fx("integrated_xbrl_TCS_cons_2026q2.xml"))
    assert s.extra["QUARTER"]["EmployeeBenefitExpense"] == D("418900000000")
    assert s.extra["YTD"]["CashFlowsFromUsedInOperatingActivities"] == D("258010000000")
    assert s.extra["INSTANT"]["Assets"] == D("1907820000000") and s.extra["INSTANT"]["Equity"] == D(
        "1199940000000"
    )


def test_dimensional_text_and_identifier_facts_are_not_kept_as_numbers():
    every = {
        k
        for scope in parse_xbrl(fx("integrated_xbrl_TCS_cons_2026q2.xml")).extra.values()
        for k in scope
    }
    assert (
        "ScripCode" not in every
        and "Symbol" not in every
        and "DateOfStartOfReportingPeriod" not in every
    )
    assert "SegmentAssets" in every  # company-level segment totals are not dimensional contexts
    assert not any(
        k.startswith("OtherExpenses") and k[-1].isdigit() for k in every
    )  # per-member lines are dimensional


def test_old_format_files_keep_their_quarter_and_year_to_date_numbers_too():
    s = parse_xbrl(fx("results_xbrl_RELIANCE_cons.xml"))
    assert s.extra["QUARTER"]["ProfitBeforeTax"] == s.quarter["pbt"] and s.extra["YTD"]


# --- details the broader tests did not pin down ---
def _rows(name: str):
    import json

    d = json.loads(fx(name))
    return d["data"] if isinstance(d, dict) else d


def test_the_integrated_listing_keeps_the_dissemination_time_and_both_links():
    import json

    rows = _rows("integrated_listing_TCS.json")
    cons = next(
        f
        for f in parse_integrated_listing(json.dumps({"data": rows}).encode())
        if f.symbol == "TCS"
    )
    assert cons.disseminated_at == datetime(2026, 10, 8, 16, 38, 10, tzinfo=UTC)  # 22:08:10 IST
    assert cons.xbrl_url == (
        "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml"
    )
    assert cons.detail_url == (
        "https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_200121_08102026220810_iXBRL_WEB.html"
    )
    bare = [
        {**r, "creation_Date": None, "xbrl": None, "ixbrl": None}
        for r in rows
        if r["symbol"] == "TCS"
    ]
    (f, *_) = parse_integrated_listing(json.dumps({"data": bare}).encode())
    assert (f.disseminated_at, f.xbrl_url, f.detail_url) == (None, None, None)


def test_the_old_listing_keeps_the_dissemination_time_and_the_cumulative_flag():
    import json

    rows = json.loads(fx("results_listing_RELIANCE.json"))
    first = parse_listing(json.dumps([rows[0]]).encode())[0]
    assert first.disseminated_at == datetime(2025, 1, 16, 14, 50, 54, tzinfo=UTC)  # 20:20:54 IST
    assert first.cumulative is False  # "Non-cumulative"
    cumulative = parse_listing(json.dumps([{**rows[0], "cumulative": "Cumulative"}]).encode())[0]
    assert cumulative.cumulative is True
    no_xbrl = parse_listing(
        json.dumps(
            [{**rows[0], "xbrl": None, "resultDetailedDataLink": "https://x/y.html"}]
        ).encode()
    )[0]
    assert (no_xbrl.xbrl_url, no_xbrl.detail_url) == (None, "https://x/y.html")


@pytest.mark.parametrize(
    "value, expected",
    [
        ("", None),
        (None, None),
        ("-", None),
        ("https://a/-", None),
        ("https://a/-/", None),
        ("https://a/b", "https://a/b"),
        ("https://a/b/", "https://a/b/"),
    ],
)
def test_a_link_that_is_empty_or_just_a_dash_is_no_link(value, expected):
    from algo.data.providers.nse_results import _link

    assert _link(value) == expected


@pytest.mark.parametrize("declaration", ["<!DOCTYPE x>", '<!ENTITY a "b">'])
def test_either_a_dtd_or_an_entity_declaration_alone_is_refused(declaration):
    raw = f'<?xml version="1.0"?>{declaration}<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>'.encode()
    with pytest.raises(XbrlError, match="DTD/entity declarations refused"):
        parse_xbrl(raw)


def test_a_typed_member_context_is_dimensional_too_and_never_a_company_total():
    typed = (
        '<xbrli:context id="OneTyped"><xbrli:entity><xbrli:segment><xbrldi:typedMember dimension="d"><x>1</x></xbrldi:typedMember>'
        "</xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2024-10-01</xbrli:startDate>"
        "<xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>"
    )
    body = (
        BASE
        + '<in-bse-fin:RevenueFromOperations contextRef="OneTyped">1</in-bse-fin:RevenueFromOperations>'
        + '<in-bse-fin:RevenueFromOperations contextRef="OneD">7</in-bse-fin:RevenueFromOperations>'
    )
    assert parse_xbrl(XML(body, typed)).quarter["revenue"] == D(7)


@pytest.mark.parametrize(
    "start, ok",
    [("2024-10-13", False), ("2024-10-12", True), ("2024-09-22", True), ("2024-09-21", False)],
)
def test_a_period_is_a_quarter_only_when_it_runs_from_80_to_100_days(start, ok):
    body = (
        BASE.replace(
            "2024-10-01</in-bse-fin:DateOfStartOfReportingPeriod>",
            f"{start}</in-bse-fin:DateOfStartOfReportingPeriod>",
        )
        + '<in-bse-fin:RevenueFromOperations contextRef="OneD">5</in-bse-fin:RevenueFromOperations>'
    )
    if ok:
        assert parse_xbrl(XML(body)).period_start == date.fromisoformat(start)
    else:
        with pytest.raises(XbrlError, match="contain no quarter"):
            parse_xbrl(XML(body))


@pytest.mark.parametrize("year_start, kept", [("2023-12-27", True), ("2023-12-26", False)])
def test_a_year_to_date_context_may_start_at_most_370_days_before_the_quarter_end(year_start, kept):
    year = (
        f'<in-bse-fin:DateOfStartOfReportingPeriod contextRef="FourD">{year_start}</in-bse-fin:DateOfStartOfReportingPeriod>'
        '<in-bse-fin:DateOfEndOfReportingPeriod contextRef="FourD">2024-12-31</in-bse-fin:DateOfEndOfReportingPeriod>'
        '<in-bse-fin:RevenueFromOperations contextRef="FourD">900</in-bse-fin:RevenueFromOperations>'
    )
    body = (
        BASE
        + '<in-bse-fin:RevenueFromOperations contextRef="OneD">5</in-bse-fin:RevenueFromOperations>'
        + year
    )
    assert parse_xbrl(XML(body)).ytd == ({"revenue": D(900)} if kept else {})


@pytest.mark.parametrize(
    "end, start",
    [
        ("2024-03-31", "2024-01-01"),
        ("2024-06-30", "2024-04-01"),
        ("2024-09-30", "2024-07-01"),
        ("2024-12-31", "2024-10-01"),
    ],
)
def test_a_quarter_start_is_derived_from_each_calendar_quarter_end(end, start):
    assert parse_xbrl(_no_start(end)).period_start == date.fromisoformat(start)


@pytest.mark.parametrize(
    "nature, basis",
    [
        ("Consolidated", "CONSOLIDATED"),
        ("Standalone", "STANDALONE"),
        ("Non-consolidated", "STANDALONE"),
    ],
)
def test_the_basis_is_read_from_the_nature_of_the_report(nature, basis):
    body = BASE.replace(">Standalone<", f">{nature}<")
    assert parse_xbrl(XML(body)).basis == basis
    with pytest.raises(XbrlError, match="neither standalone or consolidated"):
        parse_xbrl(XML(BASE.replace(">Standalone<", ">Something else<")))
