import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.data.providers.base import ParseError
from algo.data.providers.nse_corporate_actions import parse_actions, parse_subject

RAW = (Path(__file__).parents[2] / "data/nse/corporate_actions_sample.json").read_bytes()  # real


def kinds(subject):
    return [(c.kind, c.status, c.num, c.den, c.amount) for c in parse_subject(subject)]


@pytest.mark.parametrize(
    ("subject", "expected"),
    [  # real NSE subjects
        ("Bonus 1:1", [("bonus", "ok", D(2), D(1), None)]),
        (" Bonus 1:2", [("bonus", "ok", D(3), D(2), None)]),  # ITC: 1 new per 2 held => x1.5
        (" Bonus 1:3", [("bonus", "ok", D(4), D(3), None)]),  # Wipro 2019
        (
            "Bonus 2:3 And Final Dividend Rs.6/- Per Share",
            [("bonus", "ok", D(5), D(3), None), ("dividend", "ok", None, None, D(6))],
        ),
        ("Bonus 4:1", [("bonus", "ok", D(5), D(1), None)]),  # Bajaj 2025: 4 new per 1 held
        ("Face Value Split From Rs.10/- To Rs.2/-", [("split", "ok", D(10), D(2), None)]),
        (
            "Face Value Split (Sub-Division) - From Rs 2 Per Share To Rs 1 Per Share",
            [("split", "ok", D(2), D(1), None)],
        ),
        ("Face Value Split Rs 10 To Re 1", [("split", "ok", D(10), D(1), None)]),
        (
            "Bonus 1:1/Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/-",
            [("bonus", "ok", D(2), D(1), None), ("split", "ok", D(10), D(2), None)],
        ),
        (
            "Intdiv-Rs 3persh/Bonus1:1",
            [("dividend", "ok", None, None, D(3)), ("bonus", "ok", D(2), D(1), None)],
        ),
        (
            " Annual General Meeting/Dividend - Rs 2.50 Per Share/Bonus 1:10 (Revised)",
            [("dividend", "ok", None, None, D("2.50")), ("bonus", "ok", D(11), D(10), None)],
        ),
        (
            "Annual General Meeting/ Dividend - Rs 29.50/- Per Share And Bonus 1:1",
            [("dividend", "ok", None, None, D("29.50")), ("bonus", "ok", D(2), D(1), None)],
        ),
        ("Dividend-Rs.7.5/- Per Sh.", [("dividend", "ok", None, None, D("7.5"))]),
        (
            "Final Dividend Rs.4.50 Per Share And Special Centenary Dividend Rs.5.50 Per Share",
            [("dividend", "ok", None, None, D("4.50")), ("dividend", "ok", None, None, D("5.50"))],
        ),
        (
            "Dividend Final Rs 2.80 And Special Rs 1.65 Per Share",
            [("dividend", "ok", None, None, D("2.80")), ("dividend", "ok", None, None, D("1.65"))],
        ),
        (
            "Interim Dividend-Rs.2/- Per Share (Purpose Revised)",
            [("dividend", "ok", None, None, D(2))],
        ),
        (
            "Annual General Meeting And Dividend Rs.16.50 Per Share",
            [("dividend", "ok", None, None, D("16.50"))],
        ),
    ],
)
def test_real_subjects_parse_exactly(subject, expected):
    assert kinds(subject) == expected


@pytest.mark.parametrize(
    ("subject", "kind"),
    [
        ("Agm/Dividend-500%", "dividend"),  # percent of historic face value: unknown amount
        ("Interim Dividend - 200%  Purpose Revised", "dividend"),
        ("Demerger", "demerger"),
        ("Scheme Of Arrangement", "arrangement"),
        ("Buy Back", "buy"),
        ("Rights 1:15 @ Premium Rs 1247", "rights"),
        ("Distribution - Rs 2.75 Per Unit Consist Of Re 0.60 Per Unit As Interest", "distribution"),
        ("Something Brand New", "other"),
        ("Dividend", "dividend"),
        ("Face Value Split", "split"),
        ("Bonus 1:0", "bonus"),
    ],
)
def test_unpriceable_goes_to_review_never_ok(subject, kind):
    comps = parse_subject(subject)
    assert [c.kind for c in comps] == [kind] and comps[0].status == "review" and comps[0].reason


def test_rights_keeps_ratio_and_premium_for_the_reviewer():
    (c,) = parse_subject("Rights 3:19 @ Premium Rs 1090 Per Share")
    assert (c.num, c.den, c.amount) == (D(3), D(19), D(1090))
    (bare,) = parse_subject("Rights issue")
    assert (bare.num, bare.amount) == (None, None)


def test_meeting_only_is_not_an_action():
    assert parse_subject("Annual General Meeting") == [] and parse_subject("") == []


def test_real_sample_file():
    acts, skipped = parse_actions(RAW)
    assert any("ANANTAM" in s for s in skipped)  # InvIT series IV: dropped
    bj = [a for a in acts if a.symbol == "BAJFINANCE" and a.ex_date == date(2025, 6, 16)]
    assert sorted((a.comp.kind, a.comp.num, a.comp.den) for a in bj) == [
        ("bonus", D(5), D(1)), ("split", D(2), D(1))
    ]  # fmt: skip
    ic = [a for a in acts if a.symbol == "ICICIBANK" and a.ex_date == date(2017, 6, 20)]
    assert [(a.idx, a.comp.kind) for a in ic] == [(0, "dividend"), (1, "bonus")]
    assert ic[0].record_date is None  # '-' in the feed
    rel = next(a for a in acts if a.symbol == "RELIANCE" and a.ex_date == date(2009, 11, 26))
    assert rel.record_date == date(2009, 11, 27) and rel.isin == "INE002A01018"
    assert not any(a.comp.status == "ok" and a.comp.kind in ("rights", "demerger") for a in acts)


def test_row_without_ex_date_is_skipped_and_bad_json_raises():
    row = b'[{"symbol":"X","series":"EQ","subject":"Bonus 1:1","exDate":"-","recDate":"-"}]'
    acts, skipped = parse_actions(row)
    assert acts == [] and "no ex-date" in skipped[0]
    junk_date = b'[{"symbol":"X","series":"EQ","subject":"Bonus 1:1","exDate":"junk"}]'
    for bad in (b"not json", b'{"a":1}', b'[{"symbol":"X"}]', junk_date):
        with pytest.raises(ParseError):
            parse_actions(bad)


@pytest.mark.parametrize(
    ("subject", "expected"),
    [  # real subjects found in the full Nifty 200 history that the first parser missed
        ("Bonus - 1:1", [("bonus", "ok", D(2), D(1), None)]),
        ("Bonus-1:3", [("bonus", "ok", D(4), D(3), None)]),
        (
            "Bonus - 1:1 And Face Value Split From Rs. 10 To Rs. 2",
            [("bonus", "ok", D(2), D(1), None), ("split", "ok", D(10), D(2), None)],
        ),
        (
            "Div-Rs.5.50 Pr Sh/Bon 5:1purpose Revised",
            [("dividend", "ok", None, None, D("5.50")), ("bonus", "ok", D(6), D(1), None)],
        ),
        ("Dividend Rs - 9.40 Per Share", [("dividend", "ok", None, None, D("9.40"))]),
        ("Dividend Rs -7.65 Per Share", [("dividend", "ok", None, None, D("7.65"))]),
        ("Annual General Meeting/Dividend Re -1 Per Share", [("dividend", "ok", None, None, D(1))]),
        (
            "Annual General Meeting/Dividend Re- 0.40 Per Share",
            [("dividend", "ok", None, None, D("0.40"))],
        ),
        ("Annual General Meeting/Dividend Rs- 7 Per Share", [("dividend", "ok", None, None, D(7))]),
        ("Agm/Div-17.50 Per Share", [("dividend", "ok", None, None, D("17.50"))]),
        ("Dividend-Rs.29/ Per Share", [("dividend", "ok", None, None, D(29))]),
        (
            "3rd Int Div-Rs.2/- Per Shrd Revised/Purpose Revised",
            [("dividend", "ok", None, None, D(2))],
        ),
        ("Div-Fin Re.0.75+Int Re.1/Purpose Revised", [("dividend", "ok", None, None, D("1.75"))]),
        (
            "Annual General Meeting / Dividend - Rs 3/- Per Share / Bonus - 1:2",
            [("dividend", "ok", None, None, D(3)), ("bonus", "ok", D(3), D(2), None)],
        ),
        (
            "Annual General Meeting / Dividend - Rs 5.25/- Per Share / Annual Book Closure",
            [("dividend", "ok", None, None, D("5.25"))],
        ),
        (
            "Annual General Meeting/Dividend Rs.10/- Per Share/Election Of Directors",
            [("dividend", "ok", None, None, D(10))],
        ),
        (
            "Annual Book Closure And 2nd Interim Dividend Re.0.60 Per Share (Purpose Revised)",
            [("dividend", "ok", None, None, D("0.60"))],
        ),
    ],
)
def test_real_variants_found_in_full_history(subject, expected):
    assert kinds(subject) == expected


@pytest.mark.parametrize(
    "subject",
    ["Agm Purpose Revised", "Annaul General Meeting", "Annual Genaral Meeting", "Annnual General Meeting",
     "Annual Book Closure", "E-Voting", "Egm-Election Of Directors", "Elctn Of Sh. Director",
     "Annual General Meeting   Bc Dates Revised", "Annual General Meeting (Book Closure Date Revised)",
     "Annual General Meeting/ Change In Registrar And Transfer Agent", "-", "Purpose Revised"],
)  # fmt: skip
def test_meeting_and_notice_noise_is_not_an_action(subject):
    assert parse_subject(subject) == []


def test_percent_dividend_is_not_mistaken_for_a_rupee_amount():
    (c,) = parse_subject("Agm/Div-70%/Elec. Of Dir")
    assert c.status == "review" and c.amount is None  # '70' must not become Rs 70


@pytest.mark.parametrize(
    ("subject", "expected"),
    [  # real abbreviated subjects from the full Nifty 200 history
        ("Fv Splt Frm Rs 10 To Re 1", [("split", "ok", D(10), D(1), None)]),
        ("Fv Splt Frm Rs 10 To Rs 2", [("split", "ok", D(10), D(2), None)]),
        ("Fv Spl-Rs10tore1/Bon-1:1",
         [("split", "ok", D(10), D(1), None), ("bonus", "ok", D(2), D(1), None)]),
        ("Agm/Div-Rs.2/Fv Rs10tors5",
         [("dividend", "ok", None, None, D(2)), ("split", "ok", D(10), D(5), None)]),
        ("Spl Rs10 To Rs2 /Div-125%", [("split", "ok", D(10), D(2), None),
                                       ("dividend", "review", None, None, None)]),
        ("Interim Dividend 3 Per Share", [("dividend", "ok", None, None, D(3))]),
    ],
)  # fmt: skip
def test_abbreviated_real_subjects(subject, expected):
    assert kinds(subject) == expected


@pytest.mark.parametrize(
    ("subject", "kind"),
    [("Rhts Eq 2:5 & 2 Wrnt:2 Eq", "rights"), ("Right-Eq1:5 & 9ccps:10eq", "rights"),
     ("Rhs 3:7@Prem Rs95", "rights"), ("Scheme Of Arangement- Bonus - 1 Debenture For 1 Equity Share Held", "arangement"),
     ("Sch Of Agmt- Bonus Deb1:1", "sch of")],
)  # fmt: skip
def test_misspelled_rights_and_schemes_still_go_to_review_under_the_right_kind(subject, kind):
    comps = parse_subject(subject)
    assert comps[0].kind == kind and comps[0].status == "review"


def test_dividend_followed_by_ordinal_is_not_an_amount():
    (c,) = parse_subject("Dividend 2nd Interim")
    assert c.status == "review" and c.amount is None


@pytest.mark.parametrize(
    ("subject", "expected"),
    [  # real: "Spl" here means SPECIAL dividend, not split (regression from a too-greedy keyword)
        ("Spl Div-Rs.80/- Per Share", [("dividend", "ok", None, None, D(80))]),
        ("Spl Dividend-Rs2/- Per Sh", [("dividend", "ok", None, None, D(2))]),
        ("Div Int-Rs1.20+Spl-Rs1.30", [("dividend", "ok", None, None, D("2.50"))]),
        ("Div-(Fin-Rs4.5+Spl-Rs1.5)", [("dividend", "ok", None, None, D(6))]),
        ("Agm/Div-Rs.15 + Spl-Rs.20", [("dividend", "ok", None, None, D(35))]),
    ],
)
def test_spl_means_special_dividend_unless_it_carries_a_face_value_pair(subject, expected):
    assert kinds(subject) == expected


@pytest.mark.parametrize(
    "subject", ["Agm/Div Fin-130%+Spl-25%", "Div Fin-100% + Spl-25%", "Spl Interim Dividend-25%"]
)
def test_percent_special_dividends_are_dividend_review_never_split(subject):
    comps = parse_subject(subject)
    assert [c.kind for c in comps] == ["dividend"] and comps[0].status == "review"


def test_a_real_split_word_without_face_values_is_review_not_guessed():
    (c,) = parse_subject("Face Value Split")
    assert (c.kind, c.status) == ("split", "review")


def test_zero_face_value_is_review_not_a_division_by_zero():
    (c,) = parse_subject("Face Value Split From Rs 10 To Rs 0")
    assert (c.kind, c.status, c.reason) == ("split", "review", "zero face value")


def test_a_skipped_row_never_stops_the_rows_after_it():
    rows = [
        {"symbol": "A", "series": "IV", "subject": "Dividend Rs 1", "exDate": "01-Jan-2025"},
        {"symbol": "B", "series": "EQ", "subject": "Dividend Rs 2", "exDate": "-"},
        {"symbol": "C", "series": "EQ", "subject": "Bonus 1:1", "exDate": "02-Jan-2025"},
    ]
    acts, skipped = parse_actions(json.dumps(rows).encode())
    assert [(a.symbol, a.subject) for a in acts] == [("C", "Bonus 1:1")]
    assert skipped == ["A: series IV", "B: no ex-date (Dividend Rs 2)"]


def test_the_whole_subject_text_is_kept_on_every_component():
    rows = [{"symbol": "X", "series": "EQ", "subject": " Bonus 1:1/Dividend Rs 2 ",
             "exDate": "02-Jan-2025", "recDate": "03-Jan-2025", "isin": "INE000A01010"}]  # fmt: skip
    acts, _ = parse_actions(json.dumps(rows).encode())
    assert [(a.idx, a.comp.kind, a.subject, a.record_date) for a in acts] == [
        (0, "bonus", "Bonus 1:1/Dividend Rs 2", date(2025, 1, 3)),
        (1, "dividend", "Bonus 1:1/Dividend Rs 2", date(2025, 1, 3)),
    ]


def test_a_non_list_document_is_a_parse_error_with_a_clear_message():
    with pytest.raises(ParseError, match="^expected a JSON list$"):
        parse_actions(b'{"a": 1}')


@pytest.mark.parametrize(
    ("subject", "reason"),
    [
        ("Distribution - Rs 2 Per Unit", "unit distribution (non-equity)"),
        ("Bonus 1:0", "zero denominator"),
        ("Dividend", "no rupee amount"),
        ("Agm/Div-500%", "percent of face value; historic face value unknown"),
        ("Rights 1:15 @ Premium Rs 100", "subscription price needs historic face value"),
        ("Demerger", "no ratio/price in feed; manual treatment"),
        ("Brand New Thing", "unrecognised subject"),
        ("Face Value Split", "face values not found"),
        ("Face Value Split From Rs 10 To Rs 0", "zero face value"),
    ],
)
def test_review_reasons_are_exact(subject, reason):
    (c,) = parse_subject(subject)
    assert c.status == "review" and c.reason == reason
