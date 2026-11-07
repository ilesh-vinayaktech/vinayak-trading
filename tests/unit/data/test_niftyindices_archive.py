import io
import zipfile
from datetime import date

from algo.data.providers.niftyindices_archive import (
    OK,
    RETRY,
    STOP,
    backoff_seconds,
    check_zip,
    classify,
    month_end,
    month_label,
    month_range,
)  # fmt: skip


def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_month_range_is_inclusive_and_crosses_year_ends():
    assert list(month_range((2016, 11), (2017, 2))) == [
        (2016, 11),
        (2016, 12),
        (2017, 1),
        (2017, 2),
    ]
    assert len(list(month_range((2017, 1), (2026, 10)))) == 118
    assert (
        list(month_range((2020, 3), (2020, 3))) == [(2020, 3)]
        and list(month_range((2020, 4), (2020, 3))) == []
    )


def test_labels_and_month_ends():
    assert month_label(2020, 3) == "Mar 2020" and month_label(2017, 12) == "Dec 2017"
    assert month_end(2020, 2) == date(2020, 2, 29) and month_end(2021, 2) == date(2021, 2, 28)
    assert month_end(2020, 12) == date(2020, 12, 31)


def test_refusals_and_challenges_stop_and_are_never_retried():
    for status in (401, 403, 429):
        assert classify(status, "text/html", b"") == STOP
    assert classify(200, "text/html", b"<html>Please solve this CAPTCHA</html>") == STOP
    assert classify(200, "text/html", b"Access Denied") == STOP
    assert classify(404, "text/html", b"") == STOP  # unexpected: do not hammer


def test_transient_server_trouble_is_retried_and_a_normal_reply_is_ok():
    assert classify(500, "", b"") == RETRY and classify(503, "", b"") == RETRY
    assert classify(408, "", b"") == RETRY
    assert classify(200, "application/json", b'{"success":true}') == OK


def test_backoff_doubles():
    assert [backoff_seconds(n) for n in (1, 2, 3)] == [10.0, 20.0, 40.0]
    assert backoff_seconds(2, base=1.0) == 2.0


def test_a_zip_is_accepted_only_when_sound_and_holding_pdfs():
    good = check_zip(make_zip({"NIFTY_50_Mar2020.pdf": b"%PDF-1", "x.txt": b"hi"}))
    assert good.ok and good.names == ("NIFTY_50_Mar2020.pdf", "x.txt") and good.reason == ""
    assert check_zip(b"junk").reason == "not a zip file"
    assert not check_zip(b"PK\x03\x04truncated").ok
    assert check_zip(make_zip({"readme.txt": b"hi"})).reason == "no PDFs inside"
    corrupt = bytearray(make_zip({"a.pdf": b"A" * 200}))
    corrupt[40] ^= 0xFF  # flip a byte inside the stored member
    r = check_zip(bytes(corrupt))
    assert not r.ok and "corrupt member a.pdf" in r.reason


def test_each_zip_rejection_carries_its_exact_fields():
    from algo.data.providers.niftyindices_archive import ZipCheck

    assert check_zip(b"junk") == ZipCheck(False, (), "not a zip file")
    assert check_zip(make_zip({"readme.txt": b"hi"})) == ZipCheck(
        False, ("readme.txt",), "no PDFs inside"
    )
    bad = check_zip(b"PK\x03\x04truncated")
    assert bad.ok is False and bad.names == () and bad.reason.startswith("bad zip: ")
    corrupt = bytearray(make_zip({"a.pdf": b"A" * 200}))
    corrupt[40] ^= 0xFF
    assert check_zip(bytes(corrupt)) == ZipCheck(False, (), "corrupt member a.pdf")


def test_challenge_text_is_found_anywhere_in_the_first_4000_bytes_and_bad_bytes_do_not_crash():
    assert classify(200, "text/html", b"x" * 3990 + b"captcha") == STOP
    assert classify(200, "text/html", b"x" * 4000 + b"captcha") == OK  # beyond what we inspect
    assert classify(200, "text/html", b"\xff\xfe CAPTCHA") == STOP  # undecodable bytes are ignored
    assert classify(200, "application/zip", b"PK\x03\x04") == OK
