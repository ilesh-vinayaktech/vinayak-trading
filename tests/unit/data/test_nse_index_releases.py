from datetime import date
from pathlib import Path

import pytest

from algo.data.providers.nse_index_releases import (
    KIND_COMPANY_NOTICE,
    KIND_NO_STRUCTURE,
    KIND_REPLACEMENT_TABLES,
    MANUAL,
    NOT_RELEVANT,
    PARSED,
    UNSUPPORTED,
    canon,
    classify_unparsed,
    extract_pages,
    parse_date,
    parse_release,
)  # fmt: skip

FIX = Path(__file__).parents[2] / "data/nse_index"


def load(name: str) -> list[str]:
    return (FIX / f"{name}.txt").read_text().split("\f")


def test_a_periodic_review_yields_component_rows_with_page_section_and_effective_date():
    r = parse_release(load("review_2020_06_10"), date(2020, 6, 10))
    assert r.kind == KIND_REPLACEMENT_TABLES and r.effective_dates == (date(2020, 6, 26),)
    comp = r.component_rows
    out = {x.symbol for x in comp if x.action == "EXCLUDED" and x.component == "NIFTY_NEXT_50"}
    assert out == {"ASHOKLEY", "IBULHSGFIN", "L&TFH", "NIACL", "IDEA"}  # symbols with & survive
    inc = {x.symbol for x in comp if x.action == "INCLUDED" and x.component == "NIFTY_NEXT_50"}
    assert inc == {"ABBOTINDIA", "IGL", "NAUKRI", "MUTHOOTFIN", "TORNTPHARM"}
    first = next(x for x in comp if x.symbol == "ASHOKLEY")
    assert (first.page, first.section_no, first.section_name) == (1, 1, "NIFTY Next 50")
    assert first.effective_from == date(2020, 6, 26) and "ASHOKLEY" in first.raw_text
    assert any(x.section_name == "NIFTY 500" for x in r.rows if x.component is None)


def test_wrapped_company_names_still_give_the_symbol():
    r = parse_release(load("review_2020_06_10"), date(2020, 6, 10))
    irctc = [x for x in r.rows if x.symbol == "IRCTC"]
    assert irctc and {x.action for x in irctc} == {"INCLUDED"}  # one row per index it joined
    assert "NIFTY 500" in {x.section_name for x in irctc}


def test_a_release_about_other_indices_has_rows_but_no_component_rows():
    r = parse_release(load("no_component_2023_12_07"), date(2023, 12, 7))
    assert r.kind == KIND_REPLACEMENT_TABLES and r.rows and r.component_rows == ()
    assert r.effective_dates == (date(2023, 12, 29),)


def test_a_single_exclusion_notice_links_the_listing_to_its_dummy_symbol():
    r = parse_release(load("exclusion_2025_09_22"), date(2025, 9, 22))
    assert r.kind == KIND_COMPANY_NOTICE
    assert {(x.symbol, x.action, x.related_symbol) for x in r.rows} == {
        ("STLNETWORK", "EXCLUDED", "DUMMYSTLTE")
    }
    assert all(x.effective_from == date(2025, 9, 24) for x in r.rows)


def test_a_demerger_notice_adds_the_dummy_symbol_to_each_listed_index():
    r = parse_release(load("dummy_inclusion_2025_04_02"), date(2025, 4, 2))
    assert r.kind == KIND_COMPANY_NOTICE
    assert {x.symbol for x in r.rows} == {"DUMMYSIEMS"}
    assert {x.action for x in r.rows} == {"INCLUDED"}
    assert {x.component for x in r.rows if x.component} == {
        "NIFTY_100",
        "NIFTY_NEXT_50",
        "NIFTY_200",
    }
    assert all(x.effective_from == date(2025, 4, 7) for x in r.rows)


def test_a_notice_about_several_companies_is_not_guessed_at():
    r = parse_release(load("two_companies_2025_06_25"), date(2025, 6, 25))
    assert r.kind == KIND_NO_STRUCTURE and r.rows == ()


def test_narrative_and_scanned_documents_stay_manual_review():
    assert parse_release(load("narrative_2020_05_13"), date(2020, 5, 13)).kind == KIND_NO_STRUCTURE
    scanned = parse_release(load("scanned_2018_09_24"), date(2018, 9, 24))
    assert scanned.kind == KIND_NO_STRUCTURE and scanned.sections == ()


def test_a_header_date_that_disagrees_with_the_listing_is_noted():
    r = parse_release(load("exclusion_2025_09_22"), date(2025, 9, 21))
    assert any("differs from listed date" in n for n in r.notes)
    assert parse_release(load("exclusion_2025_09_22"), date(2025, 9, 22)).notes == ()


def test_index_names_map_to_canonical_components_across_spellings():
    assert canon("Nifty Next 50") == canon("NIFTY NEXT50") == "NIFTY_NEXT_50"
    assert canon("Nifty50") == "NIFTY_50"
    assert canon("NIFTY Free float Midcap 100") == "MIDCAP_100_FREE_FLOAT"
    assert canon("Nifty Midcap 100") == "MIDCAP_100"
    assert canon("NIFTY Full Midcap 100") == "MIDCAP_100_FULL"
    assert canon("Nifty 500") is None and canon("Nifty50 Shariah") is None


def test_dates_parse_with_and_without_commas_and_abbreviations():
    assert parse_date("June 26, 2020") == parse_date("June 26 2020") == date(2020, 6, 26)
    assert parse_date("Mar 3, 2021") == date(2021, 3, 3)
    assert parse_date("March\n   31,   2022") == date(2022, 3, 31)  # NSE wraps long dates
    with pytest.raises(ValueError, match="unparseable date"):
        parse_date("someday")


def test_extract_pages_reads_a_real_pdf():
    pages = extract_pages((FIX / "exclusion_2025_09_22.pdf").read_bytes())
    assert len(pages) >= 1 and "STLNETWORK" in "".join(pages)


TABLE = "\n  Sr. No.      Index Name\n     1      Nifty 200\n     2      Nifty 500\n"
HEAD = (
    "Mumbai, June 25, 2025\n Exclusion notice\n effective from June 27, 2025 (close of June 26).\n"
)


def notice(body: str, table: str = TABLE):
    return parse_release([HEAD + body + table], date(2025, 6, 25))


def test_a_bare_symbol_exclusion_is_read_when_the_sentence_is_unambiguous():
    r = notice(
        "The Committee has decided to exclude TMCV from various indices as listed hereunder effective from June 27, 2025. DUMMYX\n"
    )
    assert r.kind == KIND_COMPANY_NOTICE
    assert {x.symbol for x in r.rows} == {"TMCV"} and {x.related_symbol for x in r.rows} == {
        "DUMMYX"
    }


@pytest.mark.parametrize(
    "body",
    [
        "decided to exclude AAA from various indices. Later decided to exclude BBB from various indices.",
        "decided to exclude AAA from various indices. DUMMYONE and DUMMYTWO.",
        "decided to exclude the company from various indices.",
        "Nothing about decisions here.",
        "Dummy DUMMYONE and DUMMYTWO shall be included.",
    ],
)
def test_ambiguous_notices_are_left_for_a_person(body):
    assert notice(body).kind == KIND_NO_STRUCTURE


def test_a_notice_with_two_index_tables_is_left_for_a_person():
    assert (
        notice("decided to exclude AAA from various indices.", TABLE + TABLE).kind
        == KIND_NO_STRUCTURE
    )


def test_an_exclusion_with_no_date_after_the_decision_is_left_for_a_person():
    text = (
        "Mumbai, June 25, 2025\n effective from June 20, 2025 (old).\n decided to exclude AAA from various indices."
        + TABLE
    )
    assert parse_release([text], date(2025, 6, 25)).kind == KIND_NO_STRUCTURE


def test_a_date_wrapped_across_two_lines_is_still_the_effective_date():
    text = (
        "Mumbai, February 24, 2022\n These changes shall become effective from March\n"
        "31, 2022 (close of March 30, 2022).\n 1)  NIFTY Next 50\n The following company is being "
        "excluded:\n   Sr. No.   Company Name   Symbol\n     1   Foo Ltd.     FOO\n"
    )
    r = parse_release([text], date(2022, 2, 24))
    assert r.rows[0].effective_from == date(2022, 3, 31)


def test_one_numbered_section_can_hold_several_indices_under_sub_headings():
    text = (
        "Mumbai, February 21, 2018\n become effective from April 02, 2018 (close of March 28, 2018).\n"
        "11)   IISL had announced revision of criteria and renaming of NIFTY Free float Midcap 100\n"
        "      and NIFTY Free float Smallcap 100 indices. Replacements are being made:\n"
        "      NIFTY Free float Midcap 100 (renamed as NIFTY Midcap 100 w.e.f. April 2,\n"
        "       2018):\n The following companies are being excluded:\n"
        "  Sr. No.   Company Name   Symbol\n    1   ABB India Ltd.      ABB\n"
        " The following companies are being included:\n    1   Foo Ltd.      FOO\n"
        "      NIFTY Free float Smallcap 100 (to be renamed as NIFTY Smallcap 100 w.e.f April\n"
        " The following companies are being excluded:\n    1   Bar Ltd.      BAR\n"
    )
    r = parse_release([text], date(2018, 2, 21))
    got = {(x.symbol, x.action, x.section_name, x.component) for x in r.rows}
    assert got == {
        ("ABB", "EXCLUDED", "NIFTY Free float Midcap 100", "MIDCAP_100_FREE_FLOAT"),
        ("FOO", "INCLUDED", "NIFTY Free float Midcap 100", "MIDCAP_100_FREE_FLOAT"),
        ("BAR", "EXCLUDED", "NIFTY Free float Smallcap 100", None),  # not a Nifty 200 component
    }


def test_every_unparsed_document_gets_an_explicit_classification_and_reason():
    scanned = parse_release(load("scanned_2018_09_24"), date(2018, 9, 24))
    assert (scanned.classification, "scanned" in scanned.classification_reason) == (
        UNSUPPORTED,
        True,
    )
    assert scanned.extracted_text is not None  # kept for whoever reads it
    narrative = parse_release(load("narrative_2020_05_13"), date(2020, 5, 13))
    assert narrative.classification == MANUAL and "NIFTY 50" in narrative.classification_reason
    assert narrative.extracted_text and "null and void" in narrative.extracted_text
    two = parse_release(load("two_companies_2025_06_25"), date(2025, 6, 25))
    assert two.classification == MANUAL  # names exclusions from Nifty indices: a person reads it
    ok = parse_release(load("review_2020_06_10"), date(2020, 6, 10))
    assert ok.classification == PARSED and ok.extracted_text is None


def test_a_document_that_changes_no_component_index_is_not_relevant_but_says_why():
    label, why = classify_unparsed(
        ["Revision in criteria of NIFTY Microcap 250 index. About NSE Indices: Nifty 50"]
    )
    assert label == NOT_RELEVANT and "no constituent action" in why
    # the boilerplate footer mentions the Nifty 50 in every release and must not trigger review
    label, _ = classify_unparsed(
        ["Exclusion of X from the Smallcap index.\nAbout NSE Indices Limited ... Nifty 50 ..."]
    )
    assert label == NOT_RELEVANT
    label, _ = classify_unparsed(
        ["Replacements are being made in NIFTY 50 as listed. About NSE Indices"]
    )
    assert label == MANUAL


# ---- precision tests (each pins a detail a mutant could otherwise change) ------------------------
def tables(*blocks: str) -> str:
    return "".join(blocks)


HDR = "Mumbai, June 10, 2020\n  These changes shall become effective from June 26, 2020 (close of June 25, 2020).\n"
EXC = " The following company is being excluded:\n  Sr. No.   Company Name    Symbol\n"
INC = " The following company is being included:\n  Sr. No.   Company Name    Symbol\n"


def test_a_release_carries_its_dates_sections_company_names_and_notes():
    text = HDR + "1)  NIFTY Next 50\n" + EXC + "    1   Ashok Leyland Ltd.      ASHOKLEY\n" + INC
    text += (
        "    1   Abbott India Ltd.       ABBOTINDIA\n2)  NIFTY 500\n"
        + EXC
        + "    1   Foo Ltd.   FOO\n"
    )
    r = parse_release([text], date(2020, 6, 10))
    assert r.announced == date(2020, 6, 10) and r.kind == KIND_REPLACEMENT_TABLES
    assert r.sections == ("NIFTY Next 50", "NIFTY 500") and r.effective_dates == (
        date(2020, 6, 26),
    )
    assert r.notes == () and r.classification == PARSED
    a = r.rows[0]
    assert (a.symbol, a.company, a.action, a.section_no, a.page) == (
        "ASHOKLEY", "Ashok Leyland Ltd.", "EXCLUDED", 1, 1,
    )  # fmt: skip
    assert a.raw_text == "1   Ashok Leyland Ltd.      ASHOKLEY"
    assert [(x.symbol, x.section_no, x.component) for x in r.rows] == [
        ("ASHOKLEY", 1, "NIFTY_NEXT_50"), ("ABBOTINDIA", 1, "NIFTY_NEXT_50"), ("FOO", 2, None),
    ]  # fmt: skip


def test_rows_report_the_page_they_are_on():
    page1 = HDR + "1)  NIFTY 50\n" + EXC + "    1   Foo Ltd.    FOO\n"
    page2 = (
        " Sr. No.  Company Name  Symbol\n    2   Bar Ltd.    BAR\n2)  NIFTY Next 50\n"
        + INC
        + "    1   Baz Ltd.  BAZ\n"
    )
    r = parse_release([page1, page2], date(2020, 6, 10))
    assert [(x.symbol, x.page) for x in r.rows] == [("FOO", 1), ("BAR", 2), ("BAZ", 2)]


def test_no_inclusion_is_being_made_stops_row_attribution():
    text = (
        HDR
        + "1)  NIFTY 50\n"
        + EXC
        + "    1   Foo Ltd.    FOO\n No inclusion is being made in the index.\n"
    )
    text += "    2   Stray Ltd.    STRAY\n2)  NIFTY Next 50\n" + INC + "    1   Baz Ltd.  BAZ\n"
    r = parse_release([text], date(2020, 6, 10))
    assert [x.symbol for x in r.rows] == ["FOO", "BAZ"]  # STRAY follows 'no inclusion': not a row
    lower = text.replace("No inclusion", "no inclusion")
    assert [x.symbol for x in parse_release([lower], date(2020, 6, 10)).rows] == ["FOO", "BAZ"]


def test_each_section_takes_the_latest_effective_date_before_it_else_the_first():
    text = (
        "1)  NIFTY 50\n" + EXC + "    1   Early Ltd.   EARLY\n"  # before any date phrase
        + " effective from March 27, 2020\n2)  NIFTY Next 50\n" + EXC + "    1   Mid Ltd.   MID\n"
        + " effective from June 26, 2020\n3)  NIFTY 100\n" + EXC + "    1   Late Ltd.   LATE\n"
    )  # fmt: skip
    r = parse_release([text], date(2020, 6, 10))
    assert {x.symbol: x.effective_from for x in r.rows} == {
        "EARLY": date(2020, 3, 27),  # nothing precedes it: the first date mentioned
        "MID": date(2020, 3, 27),
        "LATE": date(2020, 6, 26),
    }
    assert r.effective_dates == (date(2020, 3, 27), date(2020, 6, 26))
    assert parse_release(["Mumbai\n1)  NIFTY 50\n" + EXC + "    1   Foo Ltd.   FOO\n"],
                         date(2020, 6, 10)).rows[0].effective_from is None  # no date anywhere  # fmt: skip


def test_the_scanned_threshold_and_reason_texts_are_exact():
    assert classify_unparsed(["x" * 39]) == (
        UNSUPPORTED,
        "no text layer (scanned image): needs OCR or manual reading",
    )
    assert classify_unparsed(["x" * 40])[0] == NOT_RELEVANT  # forty characters is text, not a scan
    assert classify_unparsed(["a" * 100]) == (
        NOT_RELEVANT,
        "no constituent action on a Nifty 200 component index",
    )
    label, why = classify_unparsed(["Replacements in NIFTY 50 follow for the periodic review."])
    assert (
        label == MANUAL
        and why == "mentions 'Replacements' and 'NIFTY 50' but has no parsable tables"
    )


def test_notice_rows_carry_their_exact_provenance():
    r = parse_release(load("dummy_inclusion_2025_04_02"), date(2025, 4, 2))
    assert r.announced == date(2025, 4, 2) and r.kind == KIND_COMPANY_NOTICE
    first = r.rows[0]
    assert (first.symbol, first.section_no, first.section_name, first.page) == (
        "DUMMYSIEMS",
        1,
        "Nifty 100",
        1,
    )
    assert (
        first.raw_text == "1      Nifty 100"
        and first.company == ""
        and first.related_symbol is None
    )
    assert r.effective_dates and date(2025, 4, 7) in r.effective_dates
    ex = parse_release(load("exclusion_2025_09_22"), date(2025, 9, 22))
    assert ex.announced == date(2025, 9, 22) and ex.rows[0].related_symbol == "DUMMYSTLTE"
    assert ex.rows[0].effective_from == date(2025, 9, 24) and ex.notes == ()


def test_pdf_extraction_gives_exactly_the_pages_and_fails_loudly_on_garbage():
    import subprocess

    pages = extract_pages((FIX / "exclusion_2025_09_22.pdf").read_bytes())
    assert len(pages) == 2 and all(p.strip() for p in pages)  # two real pages, no phantom third
    with pytest.raises(subprocess.CalledProcessError):
        extract_pages(b"this is not a pdf")


def test_lettered_section_headings_are_read_like_numbered_ones():
    r = parse_release(load("lettered_sections_2020_08_20"), date(2020, 8, 20))
    assert r.kind == KIND_REPLACEMENT_TABLES and r.effective_dates == (date(2020, 9, 25),)
    comp = {(x.component, x.action) for x in r.component_rows}
    assert {("NIFTY_50", "EXCLUDED"), ("NIFTY_50", "INCLUDED")} <= comp
    assert {("NIFTY_NEXT_50", "EXCLUDED"), ("NIFTY_NEXT_50", "INCLUDED")} <= comp
    nifty50 = [x for x in r.component_rows if x.component == "NIFTY_50"]
    assert nifty50 and all(x.effective_from == date(2020, 9, 25) for x in nifty50)
    assert {x.section_no for x in r.rows if x.component == "NIFTY_50"} == {
        101
    }  # a) -> 101, no clash
    assert {x.section_no for x in r.rows if x.component == "NIFTY_NEXT_50"} == {102}


def test_section_numbers_for_letters_never_collide_with_numbers():
    from algo.data.providers.nse_index_releases import section_number

    assert section_number("7") == 7 and section_number("a") == 101 and section_number("B") == 102
