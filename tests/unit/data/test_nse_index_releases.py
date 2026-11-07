from datetime import date
from pathlib import Path

import pytest

from algo.data.providers.nse_index_releases import (
    KIND_COMPANY_NOTICE,
    KIND_NO_STRUCTURE,
    KIND_REPLACEMENT_TABLES,
    canon,
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
