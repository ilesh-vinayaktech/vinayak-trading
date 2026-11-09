from datetime import date

import pytest

from algo.data.index_releases import store_release
from algo.data.providers.nse_index_releases import Release
from algo.data.transcriptions import TranscriptionError, store_transcription
from tests.support.bt import NOW, make_env

pytestmark = pytest.mark.integration
DOC = {
    "doc_id": "pr_scan", "announced": "2021-08-23", "effective_from": "2021-09-30",
    "source_sha256": "abc", "method": "OCR test", "verification": ["matches snapshots"],
    "rows": [
        {"page": 10, "section_no": 7, "section": "NIFTY Midcap 100", "action": "EXCLUDED",
         "symbol": "VGUARD", "company": "V-Guard Industries Ltd."},
        {"page": 10, "section_no": 7, "section": "NIFTY Midcap 100", "action": "INCLUDED",
         "symbol": "IRFC", "company": "Indian Railway Finance Corporation Ltd."},
    ],
}  # fmt: skip


def scanned(conn):
    store_release(conn, "pr_scan", Release(date(2021, 8, 23), "MANUAL_REVIEW", (), (), (), (),
                                           "UNSUPPORTED_FORMAT", "no text layer", "text"),
                  source_url="u", source_hash="abc", now=NOW)  # fmt: skip


def test_a_transcription_is_stored_provisional_and_the_scan_is_no_longer_unreadable(conn):
    make_env(conn)
    scanned(conn)
    assert store_transcription(conn, DOC, actual_sha256="abc") == 2
    rows = conn.execute(
        "SELECT symbol, action, component, effective_from, review_status, mapping_status, raw_text"
        " FROM index_release_row ORDER BY symbol").fetchall()  # fmt: skip
    assert rows == [
        ("IRFC", "INCLUDED", "MIDCAP_100", date(2021, 9, 30), "PROVISIONAL", "UNMAPPED_SYMBOL",
         "OCR: Indian Railway Finance Corporation Ltd. IRFC"),
        ("VGUARD", "EXCLUDED", "MIDCAP_100", date(2021, 9, 30), "PROVISIONAL", "UNMAPPED_SYMBOL",
         "OCR: V-Guard Industries Ltd. VGUARD"),
    ]  # fmt: skip
    cls, why, notes = conn.execute(
        "SELECT classification, classification_reason, notes FROM index_release_document"
    ).fetchone()
    assert cls == "PARSED" and "transcribed: OCR test" in why
    assert notes[0]["verification"] == ["matches snapshots"]
    assert store_transcription(conn, DOC, actual_sha256="abc") == 0  # idempotent


def test_a_transcription_of_a_different_file_or_without_checks_is_refused(conn):
    make_env(conn)
    scanned(conn)
    with pytest.raises(TranscriptionError, match="differs from the one that was transcribed"):
        store_transcription(conn, DOC, actual_sha256="other")
    with pytest.raises(TranscriptionError, match="must say how it was checked"):
        store_transcription(conn, {**DOC, "verification": []}, actual_sha256="abc")
    with pytest.raises(TranscriptionError, match="missing"):
        store_transcription(conn, {"doc_id": "x"}, actual_sha256="abc")
    with pytest.raises(TranscriptionError, match="has not been parsed yet"):
        store_transcription(conn, {**DOC, "doc_id": "pr_other"}, actual_sha256="abc")
    assert conn.execute("SELECT count(*) FROM index_release_row").fetchone()[0] == 0


def test_a_scan_that_changes_no_constituents_is_classified_not_relevant_with_its_reason(conn):
    make_env(conn)
    scanned(conn)
    none = {"doc_id": "pr_scan", "announced": "2023-06-19", "source_sha256": "abc", "method": "OCR + visual",
            "verification": ["read in full"], "rows": [], "classification": "NOT_RELEVANT",
            "summary": "consultation notice; methodology change kept on hold"}  # fmt: skip
    assert store_transcription(conn, none, actual_sha256="abc") == 0
    cls, why, notes = conn.execute(
        "SELECT classification, classification_reason, notes FROM index_release_document"
    ).fetchone()
    assert cls == "NOT_RELEVANT" and "kept on hold" in why and len(notes) == 1
    assert store_transcription(conn, none, actual_sha256="abc") == 0
    assert (
        len(conn.execute("SELECT notes FROM index_release_document").fetchone()[0]) == 1
    )  # not duplicated


@pytest.mark.parametrize(
    ("change", "msg"),
    [
        ({"classification": "PARSED"}, "no rows must be NOT_RELEVANT"),
        ({"classification": "NOT_RELEVANT", "summary": ""}, "no rows must be NOT_RELEVANT"),
        ({"classification": "WEIRD"}, "classification must be one of"),
    ],
)
def test_a_rowless_transcription_must_be_not_relevant_and_explained(conn, change, msg):
    make_env(conn)
    scanned(conn)
    base = {"doc_id": "pr_scan", "announced": "2023-06-19", "source_sha256": "abc", "method": "m",
            "verification": ["v"], "rows": [], "classification": "NOT_RELEVANT", "summary": "why"}  # fmt: skip
    with pytest.raises(TranscriptionError, match=msg):
        store_transcription(conn, {**base, **change}, actual_sha256="abc")


def test_rows_must_be_parsed_and_dated(conn):
    make_env(conn)
    scanned(conn)
    with pytest.raises(TranscriptionError, match="constituent rows is PARSED"):
        store_transcription(conn, {**DOC, "classification": "NOT_RELEVANT"}, actual_sha256="abc")
    nodate = {k: v for k, v in DOC.items() if k != "effective_from"}
    with pytest.raises(TranscriptionError, match="need their effective_from"):
        store_transcription(conn, nodate, actual_sha256="abc")


def test_a_parsed_release_can_be_supplemented_with_rows_the_parser_cannot_read(conn):
    make_env(conn)
    scanned(conn)
    doc = {
        **DOC,
        "supplement": True,
        "method": "hand transcription of a table",
        "rows": [DOC["rows"][1]],
    }
    assert store_transcription(conn, doc, actual_sha256="abc") == 1
    raw = conn.execute("SELECT raw_text FROM index_release_row").fetchone()[0]
    why = conn.execute("SELECT classification_reason FROM index_release_document").fetchone()[0]
    assert raw == "TRANSCRIBED: Indian Railway Finance Corporation Ltd. IRFC"
    assert why.startswith("supplemented by reviewed transcription: hand transcription of a table")
    assert "scanned image" not in why


def test_a_transcribed_exclusion_can_name_the_dummy_symbol_it_replaces(conn):
    make_env(conn)
    scanned(conn)
    row = {**DOC["rows"][0], "related_symbol": "DUMMYVGUARD"}
    assert (
        store_transcription(conn, {**DOC, "supplement": True, "rows": [row]}, actual_sha256="abc")
        == 1
    )
    assert (
        conn.execute("SELECT related_symbol FROM index_release_row").fetchone()[0] == "DUMMYVGUARD"
    )
    plain = conn.execute(
        "SELECT count(*) FROM index_release_row WHERE related_symbol IS NULL"
    ).fetchone()[0]
    assert plain == 0
