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
