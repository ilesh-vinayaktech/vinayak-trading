from datetime import date

import pytest

from algo.data.index_releases import store_release
from algo.data.providers.nse_index_releases import Release, Row
from algo.data.revocations import RevocationError, store_revocations
from tests.support.bt import NOW, make_env

pytestmark = pytest.mark.integration


def announced(conn):
    """An August release that announced IDEA's exclusion and CENTRALBK's inclusion in Midcap 100."""
    rows = tuple(
        Row(1, 1, "Nifty Midcap 100", "MIDCAP_100", act, sym, "Co", date(2024, 9, 30), f"{sym}")
        for act, sym in (("EXCLUDED", "IDEA"), ("INCLUDED", "CENTRALBK"))
    )
    store_release(conn, "pr_aug", Release(date(2024, 8, 23), "REPLACEMENT_TABLES", rows, (), ()),
                  source_url="u", source_hash="h1", now=NOW)  # fmt: skip


DOC = {
    "authority_doc": "pr_sep", "announced": "2024-09-25", "source_sha256": "abc",
    "method": "hand transcription", "verification": ["row grouping checked against the August rows"],
    "revocations": [
        {"section": "Nifty Midcap 100", "symbol": "IDEA", "kind": "EXCLUSION_REVOKED",
         "effective_from": "2024-09-30", "revokes_doc_id": "pr_aug", "quote": "Exclusion revoked"},
        {"section": "Nifty Midcap 100", "symbol": "CENTRALBK", "kind": "INCLUSION_REVOKED",
         "effective_from": "2024-09-30", "revokes_doc_id": "pr_aug", "quote": "Inclusion revoked"},
    ],
}  # fmt: skip


def test_revocations_are_stored_as_separate_evidence_and_leave_the_announcement_untouched(conn):
    make_env(conn)
    announced(conn)
    before = conn.execute("SELECT count(*) FROM index_release_row").fetchone()[0]
    assert store_revocations(conn, DOC, actual_sha256="abc", now=NOW) == 2
    rows = conn.execute(
        "SELECT doc_id, component, symbol, kind, effective_from, authority_doc, authority_date,"
        " authority_quote FROM index_release_revocation ORDER BY symbol"
    ).fetchall()  # fmt: skip
    assert rows == [
        ("pr_aug", "MIDCAP_100", "CENTRALBK", "INCLUSION_REVOKED", date(2024, 9, 30), "pr_sep",
         date(2024, 9, 25), "Inclusion revoked"),
        ("pr_aug", "MIDCAP_100", "IDEA", "EXCLUSION_REVOKED", date(2024, 9, 30), "pr_sep",
         date(2024, 9, 25), "Exclusion revoked"),
    ]  # fmt: skip
    assert conn.execute("SELECT count(*) FROM index_release_row").fetchone()[0] == before
    assert store_revocations(conn, DOC, actual_sha256="abc", now=NOW) == 0  # idempotent


def test_a_revocation_must_match_an_announced_change_and_be_checked(conn):
    make_env(conn)
    announced(conn)
    one = DOC["revocations"][0]

    def with_(**kw):
        return {**DOC, "revocations": [{**one, **kw}]}

    with pytest.raises(RevocationError, match="differs from the one that was transcribed"):
        store_revocations(conn, DOC, actual_sha256="other", now=NOW)
    with pytest.raises(RevocationError, match="must say how it was checked"):
        store_revocations(conn, {**DOC, "verification": []}, actual_sha256="abc", now=NOW)
    with pytest.raises(RevocationError, match="missing"):
        store_revocations(conn, {"authority_doc": "x"}, actual_sha256="abc", now=NOW)
    with pytest.raises(RevocationError, match="kind must be"):
        store_revocations(conn, with_(kind="REVERSED"), actual_sha256="abc", now=NOW)
    with pytest.raises(RevocationError, match="not a Nifty 200 component"):
        store_revocations(conn, with_(section="Nifty Alpha 50"), actual_sha256="abc", now=NOW)
    with pytest.raises(RevocationError, match="no announced EXCLUDED row"):
        store_revocations(conn, with_(symbol="NOSUCH"), actual_sha256="abc", now=NOW)
    with pytest.raises(RevocationError, match="no announced INCLUDED row"):
        store_revocations(conn, with_(kind="INCLUSION_REVOKED"), actual_sha256="abc", now=NOW)
    with pytest.raises(RevocationError, match="before it was announced"):
        store_revocations(conn, {**DOC, "announced": "2024-08-01",
                                 "revocations": [one]}, actual_sha256="abc", now=NOW)  # fmt: skip
    with pytest.raises(RevocationError, match="after the change took effect"):
        store_revocations(conn, {**DOC, "announced": "2024-10-01",
                                 "revocations": [one]}, actual_sha256="abc", now=NOW)  # fmt: skip
    assert conn.execute("SELECT count(*) FROM index_release_revocation").fetchone()[0] == 0
