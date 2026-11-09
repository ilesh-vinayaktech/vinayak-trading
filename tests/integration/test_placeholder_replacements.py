from datetime import date

import pytest

from algo.data.index_releases import store_release
from algo.data.placeholder_replacements import ReplacementError, store_replacements
from algo.data.providers.nse_index_releases import Release, Row
from tests.support.bt import NOW, make_env

pytestmark = pytest.mark.integration


def releases(conn):
    inc = Row(1, 1, "Nifty 50", "NIFTY_50", "INCLUDED", "DUMMYITC", "Co", date(2025, 1, 6), "x")
    exc = Row(1, 1, "Nifty 50", "NIFTY_50", "EXCLUDED", "ITCHOTELS", "Co", date(2025, 2, 10), "y",
              "DUMMYITC")  # fmt: skip
    store_release(conn, "pr_inc", Release(date(2024, 12, 30), "COMPANY_NOTICE", (inc,), (), ()),
                  source_url="u", source_hash="h1", now=NOW)  # fmt: skip
    store_release(conn, "pr_exc", Release(date(2025, 2, 6), "COMPANY_NOTICE", (exc,), (), ()),
                  source_url="u", source_hash="h2", now=NOW)  # fmt: skip


ONE = {"placeholder": "DUMMYITC", "symbol": "ITCHOTELS", "listed_on": "2025-01-29",
       "quote": "ITC Hotels Ltd. (ITCHOTELS) was listed on January 29, 2025"}  # fmt: skip
DOC = {"evidence_doc": "pr_exc", "announced": "2025-02-06", "source_sha256": "abc",
       "method": "hand transcription", "verification": ["sentence read in the release"],
       "replacements": [ONE]}  # fmt: skip


def test_a_replacement_is_stored_once_with_its_quote(conn):
    make_env(conn)
    releases(conn)
    assert store_replacements(conn, DOC, actual_sha256="abc", now=NOW) == 1
    row = conn.execute(
        "SELECT evidence_doc, placeholder, symbol, listed_on, quote FROM index_placeholder_replacement"
    ).fetchone()
    assert row == ("pr_exc", "DUMMYITC", "ITCHOTELS", date(2025, 1, 29), ONE["quote"])
    assert store_replacements(conn, DOC, actual_sha256="abc", now=NOW) == 0  # idempotent


def test_a_replacement_the_releases_do_not_support_is_refused(conn):
    make_env(conn)
    releases(conn)

    def with_(**kw):
        return {**DOC, "replacements": [{**ONE, **kw}]}

    with pytest.raises(ReplacementError, match="differs from the one that was transcribed"):
        store_replacements(conn, DOC, actual_sha256="other", now=NOW)
    with pytest.raises(ReplacementError, match="must say how it was checked"):
        store_replacements(conn, {**DOC, "verification": []}, actual_sha256="abc", now=NOW)
    with pytest.raises(ReplacementError, match="missing"):
        store_replacements(conn, {"evidence_doc": "x"}, actual_sha256="abc", now=NOW)
    with pytest.raises(ReplacementError, match="has no exclusion of NOSUCH naming DUMMYITC"):
        store_replacements(conn, with_(symbol="NOSUCH"), actual_sha256="abc", now=NOW)
    with pytest.raises(ReplacementError, match="not between the placeholder's inclusion"):
        store_replacements(conn, with_(listed_on="2025-01-01"), actual_sha256="abc", now=NOW)
    with pytest.raises(ReplacementError, match="not between the placeholder's inclusion"):
        store_replacements(conn, with_(listed_on="2025-02-10"), actual_sha256="abc", now=NOW)
    gone = {**DOC, "replacements": [{**ONE, "placeholder": "DUMMYZZZ"}]}
    with pytest.raises(ReplacementError, match="has no exclusion of ITCHOTELS naming DUMMYZZZ"):
        store_replacements(conn, gone, actual_sha256="abc", now=NOW)
    assert conn.execute("SELECT count(*) FROM index_placeholder_replacement").fetchone()[0] == 0


def test_a_placeholder_never_included_cannot_be_replaced(conn):
    make_env(conn)
    exc = Row(1, 1, "Nifty 50", "NIFTY_50", "EXCLUDED", "ITCHOTELS", "Co", date(2025, 2, 10), "y",
              "DUMMYITC")  # fmt: skip
    store_release(conn, "pr_exc", Release(date(2025, 2, 6), "COMPANY_NOTICE", (exc,), (), ()),
                  source_url="u", source_hash="h2", now=NOW)  # fmt: skip
    with pytest.raises(ReplacementError, match="inclusion \\(None\\)"):
        store_replacements(conn, DOC, actual_sha256="abc", now=NOW)


def test_a_pre_alias_entity_carrying_the_listings_own_symbol_can_be_replaced(conn):
    make_env(conn)
    inc = Row(1, 1, "Nifty 50", "NIFTY_50", "INCLUDED", "JIOFIN", "Co", date(2023, 7, 20), "x")
    exc = Row(1, 1, "Nifty 50", "NIFTY_50", "EXCLUDED", "JIOFIN", "Co", date(2023, 9, 7), "y")
    store_release(conn, "pr_inc", Release(date(2023, 7, 17), "COMPANY_NOTICE", (inc,), (), ()),
                  source_url="u", source_hash="h1", now=NOW)  # fmt: skip
    store_release(conn, "pr_exc", Release(date(2023, 9, 5), "COMPANY_NOTICE", (exc,), (), ()),
                  source_url="u", source_hash="h2", now=NOW)  # fmt: skip
    one = {"placeholder": "JIOFIN", "symbol": "JIOFIN", "listed_on": "2023-08-21",
           "quote": "listed on August 21, 2023"}  # fmt: skip
    assert (
        store_replacements(conn, {**DOC, "replacements": [one]}, actual_sha256="abc", now=NOW) == 1
    )
    other = {**DOC, "replacements": [{**one, "placeholder": "OTHERSYM"}]}
    with pytest.raises(ReplacementError, match="has no exclusion of JIOFIN naming OTHERSYM"):
        store_replacements(conn, other, actual_sha256="abc", now=NOW)
