import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from algo.data.index_monthly import parse_archive, select_pdfs, stem, store_snapshot
from algo.data.providers.nse_index_monthly import extract_words, parse_snapshot
from tests.support.bt import NOW, make_env

pytestmark = pytest.mark.integration
FIX = Path(__file__).parents[1] / "data/nse_index_monthly"


def make_zip(names_to_files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, fixture in names_to_files.items():
            z.writestr(name, (FIX / fixture).read_bytes() if fixture else b"%PDF-other")
    return buf.getvalue()


def test_file_names_from_every_era_normalise_to_the_same_stem():
    assert {stem(n) for n in ("NIFTY_Next_50_Mar2020.pdf", "niftynext50_Jan2017.pdf")} == {
        "niftynext50"
    }
    assert stem("NIFTY_Free_Float_Midcap_100_Sep2017.pdf") == "niftyfreefloatmidcap100"
    assert stem("NIFTY_Tata_Group_25%_Cap_Sep2017.pdf") == "niftytatagroup25cap"
    assert (
        stem("nifty200_Dec2018.pdf") == "nifty200"
        and stem("sub/NIFTY_50_June2019.pdf") == "nifty50"
    )


def test_only_the_wanted_indices_are_selected_and_the_rest_are_left_alone():
    names = ["NIFTY_50_Mar2020.pdf", "NIFTY_Bank_Mar2020.pdf", "NIFTY_Full_Midcap_100_Sep2017.pdf",
             "niftymidcap100_Jan2017.pdf", "NIFTY_Midcap_150_Mar2020.pdf", "notes.txt", "NIFTY_200_Mar2020.pdf"]  # fmt: skip
    got = select_pdfs(names)
    assert got == {"NIFTY_50": "NIFTY_50_Mar2020.pdf", "MIDCAP_100_FULL": "NIFTY_Full_Midcap_100_Sep2017.pdf",
                   "MIDCAP_100": "niftymidcap100_Jan2017.pdf", "NIFTY_200": "NIFTY_200_Mar2020.pdf"}  # fmt: skip


def test_snapshots_are_stored_with_provenance_and_symbols_resolved_as_of_the_report_date(conn):
    _, a, _ = make_env(conn)
    conn.execute(
        "INSERT INTO instrument_alias VALUES (%s,'nse','ADANIPORTS',NULL,'2000-01-01',NULL)", (a,)
    )
    snap = parse_snapshot(extract_words((FIX / "NIFTY_50_Mar2020.pdf").read_bytes()))
    n = store_snapshot(
        conn, snap, zip_hash="z", pdf_name="NIFTY_50_Mar2020.pdf", pdf_hash="p", now=NOW
    )
    assert (
        n == 50
        and store_snapshot(conn, snap, zip_hash="z", pdf_name="x", pdf_hash="p", now=NOW) == 0
    )
    meta = conn.execute("SELECT index_name, component, as_of, zip_hash, pdf_name, pdf_hash, problems"
                        " FROM index_monthly_snapshot").fetchone()  # fmt: skip
    assert meta == ("NIFTY 50", "NIFTY_50", date(2020, 3, 31), "z", "NIFTY_50_Mar2020.pdf", "p", [])
    ports = conn.execute("SELECT instrument_id, mapping_status, weight, page FROM index_monthly_constituent"
                         " WHERE symbol='ADANIPORTS'").fetchone()  # fmt: skip
    assert ports[0] == a and ports[1] == "MAPPED" and float(ports[2]) == 0.54 and ports[3] == 1
    unmapped = conn.execute(
        "SELECT count(*) FROM index_monthly_constituent WHERE mapping_status<>'MAPPED'"
    ).fetchone()[0]
    assert unmapped == 49  # everything else is visible as unresolved, not dropped


def test_an_archive_is_parsed_into_its_wanted_indices_and_mismatched_titles_are_reported(conn):
    make_env(conn)
    z = make_zip({"NIFTY_50_Mar2020.pdf": "NIFTY_50_Mar2020.pdf",
                  "NIFTY_Midcap_100_Mar2020.pdf": "NIFTY_Midcap_100_Mar2020.pdf",
                  "NIFTY_Next_50_Mar2020.pdf": "NIFTY_50_Mar2020.pdf",  # name says Next 50, title says 50
                  "NIFTY_Bank_Mar2020.pdf": ""})  # fmt: skip
    stored, problems = parse_archive(conn, z, NOW)
    assert sorted(stored) == ["NIFTY 50", "NIFTY Midcap 100"]
    assert problems == [
        "NIFTY_Next_50_Mar2020.pdf: file name says NIFTY_NEXT_50, title says NIFTY_50"
    ]


def test_an_unreadable_pdf_is_reported_and_does_not_stop_the_others(conn):
    make_env(conn)
    z = make_zip({"NIFTY_50_Mar2020.pdf": "NIFTY_50_Mar2020.pdf", "NIFTY_200_Mar2020.pdf": ""})
    stored, problems = parse_archive(conn, z, NOW)
    assert (
        stored == ["NIFTY 50"]
        and len(problems) == 1
        and problems[0].startswith("NIFTY_200_Mar2020.pdf:")
    )
