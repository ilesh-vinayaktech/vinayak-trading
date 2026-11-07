from datetime import date
from pathlib import Path

import pytest

from algo.data.index_releases import store_release, unresolved
from algo.data.providers.nse_index_releases import parse_release
from tests.support.bt import NOW, make_env

pytestmark = pytest.mark.integration
FIX = Path(__file__).parents[1] / "data/nse_index"


def rel(name, d):
    return parse_release((FIX / f"{name}.txt").read_text().split("\f"), d)


def store(conn, doc, r):
    return store_release(conn, doc, r, source_url="https://x/" + doc, source_hash="h", now=NOW)


def test_rows_are_stored_provisional_with_provenance_and_stored_once(conn):
    make_env(conn)
    r = rel("review_2020_06_10", date(2020, 6, 10))
    n = store(conn, "pr_a", r)
    assert n == len(r.rows) and store(conn, "pr_a", r) == 0  # idempotent per doc + parser version
    row = conn.execute(
        "SELECT page, section_name, component, action, effective_from, raw_text, review_status,"
        " mapping_status FROM index_release_row WHERE symbol='ASHOKLEY'"
    ).fetchone()
    assert row[:5] == (1, "NIFTY Next 50", "NIFTY_NEXT_50", "EXCLUDED", date(2020, 6, 26))
    assert "ASHOKLEY" in row[5] and row[6] == "PROVISIONAL" and row[7] == "UNMAPPED_SYMBOL"


def test_known_symbols_map_to_permanent_instrument_ids_and_dummies_are_flagged(conn):
    _, a, _ = make_env(conn)
    conn.execute(
        "INSERT INTO instrument_alias VALUES (%s,'nse','SIEMENS',NULL,'2000-01-01',NULL)", (a,)
    )
    store(conn, "pr_s", rel("dummy_inclusion_2025_04_02", date(2025, 4, 2)))
    st = dict(conn.execute("SELECT symbol, mapping_status FROM index_release_row").fetchall())
    assert st == {"DUMMYSIEMS": "PLACEHOLDER_SECURITY"}  # never a normal tradable instrument
    store(conn, "pr_e", rel("exclusion_2025_09_22", date(2025, 9, 22)))
    conn.execute(
        "INSERT INTO instrument_alias VALUES (%s,'nse','STLNETWORK',NULL,'2024-01-01',NULL)", (a,)
    )
    store(conn, "pr_e2", rel("exclusion_2025_09_22", date(2025, 9, 22)).__class__(
        date(2025, 9, 22), "COMPANY_NOTICE", rel("exclusion_2025_09_22", date(2025, 9, 22)).rows,
        (), (), ()))  # fmt: skip
    mapped = conn.execute(
        "SELECT instrument_id FROM index_release_row WHERE doc_id='pr_e2' AND symbol='STLNETWORK'"
    ).fetchone()
    assert mapped[0] == a


def test_unresolved_lists_manual_documents_and_unmapped_component_rows(conn):
    make_env(conn)
    store(conn, "pr_manual", rel("narrative_2020_05_13", date(2020, 5, 13)))
    store(conn, "pr_review", rel("review_2020_06_10", date(2020, 6, 10)))
    store(conn, "pr_other", rel("no_component_2023_12_07", date(2023, 12, 7)))
    u = unresolved(conn)
    assert u["manual_documents"] == [("pr_manual", "2020-05-13")]
    syms = {r[1] for r in u["unmapped_rows"]}
    assert "ASHOKLEY" in syms and "BPCL" not in syms  # non-component rows are not chased
