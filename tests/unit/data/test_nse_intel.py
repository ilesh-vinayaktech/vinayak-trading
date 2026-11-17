# ruff: noqa: E501
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from algo.data import nse_intel as n
from algo.data.providers.base import ParseError

DEALS = (
    b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
    b"16-NOV-2026,AAA,AAA Ltd,Some Client LLP,BUY,435000,92.20,-\n"
    b'16-NOV-2026,AAA,AAA Ltd,Other Client,sell,"1,000",92.50,Pledge\n'
)


def test_deals_parse_side_numbers_and_remarks():
    rows = n.parse_deals(DEALS, "bulk")
    assert rows[0] == (
        "bulk",
        date(2026, 11, 16),
        "AAA",
        "Some Client LLP",
        "BUY",
        Decimal(435000),
        Decimal("92.20"),
        None,
    )
    assert rows[1][4:] == ("SELL", Decimal(1000), Decimal("92.50"), "Pledge")


def test_deals_no_records_is_empty_and_bad_rows_raise():
    assert n.parse_deals(b"Date,Symbol\nNO RECORDS,\n", "block") == []
    with pytest.raises(ParseError, match="missing column"):
        n.parse_deals(b"Date,Symbol\n16-NOV-2026,AAA\n", "bulk")
    bad = DEALS.replace(b"BUY", b"HOLD")
    with pytest.raises(ParseError, match="bad deal row"):
        n.parse_deals(bad, "bulk")


def test_fii_dii():
    raw = json.dumps(
        [
            {
                "category": "DII",
                "date": "16-Nov-2026",
                "buyValue": "11752.03",
                "sellValue": "15271.08",
                "netValue": "-3519.05",
            },
            {
                "category": "FII/FPI",
                "date": "16-Nov-2026",
                "buyValue": "15636.88",
                "sellValue": "10772.2",
                "netValue": "4864.68",
            },
        ]
    ).encode()
    rows = n.parse_fii_dii(raw)
    assert rows[1] == (
        date(2026, 11, 16),
        "FII",
        Decimal("15636.88"),
        Decimal("10772.2"),
        Decimal("4864.68"),
    )
    assert rows[0][1] == "DII" and rows[0][4] == Decimal("-3519.05")
    for bad in (
        b'[{"category":"X"}]',
        b'[{"category":"DII","date":"x","buyValue":"1","sellValue":"1","netValue":"1"}]',
    ):
        with pytest.raises(ParseError):
            n.parse_fii_dii(bad)


def test_insider_parses_and_converts_ist_to_utc():
    raw = json.dumps(
        {
            "data": [
                {
                    "did": 7,
                    "symbol": "RELIANCE",
                    "acqName": "A B",
                    "personCategory": "Promoters",
                    "tdpTransactionType": "Sell",
                    "acqMode": "Market Sale",
                    "secType": "Equity Shares",
                    "secAcq": "2320",
                    "secVal": "3294168",
                    "befAcqSharesNo": "3920",
                    "befAcqSharesPer": "-",
                    "afterAcqSharesNo": "1600",
                    "afterAcqSharesPer": "0.01",
                    "acqfromDt": "13-Feb-2026",
                    "acqtoDt": "13-Feb-2026",
                    "intimDt": "16-Feb-2026",
                    "date": "18-Feb-2026 19:06",
                    "xbrl": "-",
                }
            ]
        }
    ).encode()
    (r,) = n.parse_insider(raw)
    assert r[0] == "7" and r[4] == "Sell" and r[7] == Decimal(2320) and r[10] is None
    assert r[16] == datetime(2026, 2, 18, 13, 36, tzinfo=UTC) and r[17] is None
    assert n.parse_insider(b'{"acqNameList":[],"data":[]}') == []
    with pytest.raises(ParseError):
        n.parse_insider(b'{"data":[{"symbol":"X"}]}')


def test_shareholding():
    raw = json.dumps(
        [
            {
                "recordId": 216395,
                "symbol": "AVL",
                "isin": "INE679V01027",
                "date": "30-SEP-2026",
                "pr_and_prgrp": "47.14",
                "public_val": "52.86",
                "employeeTrusts": "0",
                "submissionDate": "16-NOV-2026",
                "broadcastDate": "16-NOV-2026 14:34:19",
                "revisedData": "Y",
                "xbrl": "https://x/y.xml",
            }
        ]
    ).encode()
    (r,) = n.parse_shareholding(raw)
    assert r[:4] == ("216395", "AVL", "INE679V01027", date(2026, 9, 30))
    assert (
        r[4] == Decimal("47.14")
        and r[8] == datetime(2026, 11, 16, 9, 4, 19, tzinfo=UTC)
        and r[9] is True
    )
    with pytest.raises(ParseError, match="bad period"):
        n.parse_shareholding(b'[{"recordId":1,"symbol":"A","date":"-"}]')
    with pytest.raises(ParseError):
        n.parse_shareholding(b'{"not":"a list"}')
    with pytest.raises(ParseError):
        n.parse_shareholding(b"not json")


def test_helpers_tolerate_junk():
    assert n._num("abc") is None and n._date("garbage") is None and n._ist_to_utc("garbage") is None
    assert n._date(None) is None and n._ist_to_utc("-") is None and n._text("  ") is None
    assert n._date("16-Nov-2026 10:00") == date(2026, 11, 16)


def test_shareholding_split_reads_only_single_category_facts_as_percent():
    xbrl = b"""<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:s="urn:s">
    <xbrli:context id="fii"><xbrli:entity/><xbrli:scenario><xbrldi:explicitMember dimension="s:CategoryOfShareholdersAxis">s:InstitutionsForeignMember</xbrldi:explicitMember></xbrli:scenario></xbrli:context>
    <xbrli:context id="dii"><xbrli:scenario><xbrldi:explicitMember dimension="s:CategoryOfShareholdersAxis">s:InstitutionsDomesticMember</xbrldi:explicitMember></xbrli:scenario></xbrli:context>
    <xbrli:context id="two"><xbrli:scenario><xbrldi:explicitMember dimension="s:CategoryOfShareholdersAxis">s:InstitutionsForeignMember</xbrldi:explicitMember><xbrldi:explicitMember dimension="s:Other">s:X</xbrldi:explicitMember></xbrli:scenario></xbrli:context>
    <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="fii">0.1667</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
    <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="dii">0.2172</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
    <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="two">0.9</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
    <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="missing">0.5</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
    </xbrli:xbrl>"""
    got = n.parse_shareholding_split(xbrl)
    assert got["fii_pct"] == Decimal("16.67") and got["dii_pct"] == Decimal("21.72")
    assert got["mf_pct"] is None and got["retail_pct"] is None
    with pytest.raises(ParseError, match="no shareholder-category"):
        n.parse_shareholding_split(b'<a xmlns:xbrli="http://www.xbrl.org/2003/instance"/>')
    with pytest.raises(ParseError, match="bad XBRL"):
        n.parse_shareholding_split(b"<not xml")


def _nf(name, ctx, val, extra=""):
    return (
        f"<ix:nonFraction name='in-bse-co:{name}' contextRef='{ctx}' {extra}>{val}</ix:nonFraction>"
    )


def _nn(name, ctx, val):
    return f"<ix:nonNumeric name='in-bse-co:{name}' contextRef='{ctx}'>{val}</ix:nonNumeric>"


def _filing(*persons):
    body = _nn("Symbol", "MainI", "NAUKRI") + _nn("NameOfTheCompany", "MainI", "Info Edge")
    for i, (who, kind, qty) in enumerate(persons, 1):
        c = f"Disclosure{i}"
        body += (
            _nn("NameOfThePerson", c, who)
            + _nn("CategoryOfPerson", c, "Promoter")
            + _nn("SecuritiesAcquiredOrDisposedTransactionType", c, kind)
            + _nn("ModeOfAcquisitionOrDisposal", c, "ESOP")
            + _nf("SecuritiesAcquiredOrDisposedNumberOfSecurity", c, qty)
            + _nf("SecuritiesAcquiredOrDisposedValueOfSecurity", c, "2,130.00")
            + _nf("SecuritiesHeldPriorToAcquisitionOrDisposalNumberOfSecurity", c, "407132")
            + _nf(
                "SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding",
                c,
                "0.06",
                "scale='-2'",
            )
            + _nn(
                "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate",
                c,
                "13-11-2026",
            )
            + _nn("DateOfIntimationToCompany", c, "16-11-2026")
        )
    return f"<html xmlns:ix='x'>{body}</html>".encode()


def test_insider_index_and_filing_detail():
    raw = json.dumps(
        {
            "data": [
                {
                    "appId": "4413",
                    "symbol": "NAUKRI",
                    "companyName": "Info Edge",
                    "regulation": "Regulation 7 (2)",
                    "typeOfSubmission": "Original",
                    "prevAppId": None,
                    "broadcastDateTime": "17-Nov-2026 12:38:13",
                    "ixbrl": "https://x/y.html",
                },
            ]
        }
    ).encode()
    (r,) = n.parse_pit_index(raw)
    assert (
        r[:2] == ("4413", "NAUKRI")
        and r[5] is None
        and r[6] == datetime(2026, 11, 17, 7, 8, 13, tzinfo=UTC)
    )
    assert n.parse_pit_index(b'{"data":null}') == []
    for bad in (b"nope", b'{"data":[{"symbol":"X"}]}'):
        with pytest.raises(ParseError):
            n.parse_pit_index(bad)
    at = datetime(2026, 11, 17, 7, tzinfo=UTC)
    a, b = n.parse_pit_detail(
        "4413", _filing(("Trust A", "Sell", "1065"), ("Person B", "Buy", "5")), at, "u"
    )
    assert a[0] == "4413:Disclosure1" and a[1] == "NAUKRI" and a[2] == "Trust A" and a[4] == "Sell"
    assert (
        a[7] == Decimal(1065)
        and a[8] == Decimal("2130.00")
        and a[9] == Decimal(407132)
        and a[12] == Decimal("0.06")
    )
    assert (
        a[13] == date(2026, 11, 13) and a[15] == date(2026, 11, 16) and a[16] == at and a[17] == "u"
    )
    assert b[0] == "4413:Disclosure2" and b[4] == "Buy"
    with pytest.raises(ParseError, match="no disclosure"):
        n.parse_pit_detail("1", b"<html/>", at, "u")


def test_deals_parse_the_report_page_download_too():
    raw = (
        '﻿"Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ","Quantity Traded ","Trade Price / Wght. Avg. Price ","Remarks "\n'
        '"11-NOV-2026","AAATECH","AAA Technologies Limited","VAIBHAV DOSHI","BUY","66,829","93.89","-"\n'
        '"NO RECORDS","","","","","","",""\n'
    ).encode()
    (r,) = n.parse_deals(raw, "bulk")
    assert r == (
        "bulk",
        date(2026, 11, 11),
        "AAATECH",
        "VAIBHAV DOSHI",
        "BUY",
        Decimal(66829),
        Decimal("93.89"),
        None,
    )


def test_shareholding_history_can_skip_a_filing_with_no_period():
    raw = (
        b'[{"recordId":1,"symbol":"A","date":"-"},{"recordId":2,"symbol":"B","date":"30-SEP-2021"}]'
    )
    assert [r[1] for r in n.parse_shareholding(raw, skip_undated=True)] == ["B"]
    with pytest.raises(ParseError, match="bad period"):
        n.parse_shareholding(raw)
