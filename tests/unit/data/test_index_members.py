"""Reading the official constituent lists out of the lake: the newest list wins, a missing one is None, and every index we map has a published file name."""

from datetime import date

from algo.data import index_members

CSV = "Company Name,Industry,Symbol,Series,ISIN Code\nHDFC Bank Ltd.,Financial Services,HDFCBANK,EQ,INE040A01034\nICICI Bank Ltd.,Financial Services,ICICIBANK,EQ,INE090A01021\n"


def put(root, dataset, day, version, text):
    folder = root / "raw/niftyindices" / dataset / f"dt={day}"
    folder.mkdir(parents=True)
    (folder / f"v{version:04d}.bin").write_bytes(b"\xef\xbb\xbf" + text.encode())


def test_the_newest_list_is_read_with_its_date_and_a_byte_order_mark_is_ignored(tmp_path):
    put(tmp_path, "niftybank_list", "2026-11-01", 1, CSV.replace("ICICIBANK", "OLD"))
    put(tmp_path, "niftybank_list", "2026-11-17", 1, CSV)
    day, rows = index_members.members(tmp_path, "NIFTY BANK")
    assert day == date(2026, 11, 17)
    assert [(m.symbol, m.isin, m.industry) for m in rows] == [
        ("HDFCBANK", "INE040A01034", "Financial Services"),
        ("ICICIBANK", "INE090A01021", "Financial Services"),
    ]


def test_the_highest_version_of_a_day_is_used(tmp_path):
    put(tmp_path, "niftybank_list", "2026-11-17", 1, CSV.replace("ICICIBANK", "OLD"))
    folder = tmp_path / "raw/niftyindices/niftybank_list/dt=2026-11-17"
    (folder / "v0002.bin").write_bytes(CSV.encode())
    assert [m.symbol for m in index_members.members(tmp_path, "NIFTY BANK")[1]] == [
        "HDFCBANK",
        "ICICIBANK",
    ]


def test_an_index_with_no_list_or_no_stored_file_has_no_members(tmp_path):
    assert (
        index_members.members(tmp_path, "SENSEX") is None
    )  # BSE index: NSE publishes no list for it
    assert index_members.members(tmp_path, "NIFTY BANK") is None  # mapped, but never captured
    (tmp_path / "raw/niftyindices/niftybank_list/dt=2026-11-17").mkdir(parents=True)
    assert index_members.members(tmp_path, "NIFTY BANK") is None  # a day folder with no file


def test_every_mapped_index_has_a_file_to_fetch_and_no_file_is_unused():
    assert set(index_members.LISTS.values()) == set(index_members.FILES)
