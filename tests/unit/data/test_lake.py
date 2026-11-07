from datetime import UTC, date, datetime

import pytest

from algo.data.lake import IntegrityError, LocalLake

D = date(2026, 1, 5)
NOW = datetime(2026, 1, 5, 13, 0, tzinfo=UTC)


def put(lake, data=b"a", kind="initial"):
    return lake.put("nse", "bhav", D, data, url="u", fetched_at=NOW, ingest_kind=kind)


def test_roundtrip_and_layout(tmp_path):
    lake = LocalLake(tmp_path)
    m = put(lake)
    assert m.version == 1 and m.size == 1
    assert lake.get(m) == b"a"
    assert (tmp_path / "raw/nse/bhav/dt=2026-01-05/v0001.bin").exists()


def test_identical_payload_is_idempotent_changed_payload_is_new_version(tmp_path):
    lake = LocalLake(tmp_path)
    m1, again = put(lake), put(lake)
    assert again == m1 and len(lake.versions("nse", "bhav", D)) == 1
    m2 = put(lake, b"b", "provider_correction")
    assert m2.version == 2 and m2.ingest_kind == "provider_correction"
    assert lake.get(m1) == b"a" and lake.get(m2) == b"b"  # original untouched


def test_tamper_detected(tmp_path):
    lake = LocalLake(tmp_path)
    m = put(lake)
    (tmp_path / "raw/nse/bhav/dt=2026-01-05/v0001.bin").write_bytes(b"evil")
    with pytest.raises(IntegrityError):
        lake.get(m)


def test_bad_kind_and_naive_time(tmp_path):
    lake = LocalLake(tmp_path)
    with pytest.raises(ValueError):
        put(lake, kind="whatever")
    with pytest.raises(ValueError):
        lake.put("nse", "bhav", D, b"x", url="u", fetched_at=datetime(2026, 1, 5))  # noqa: DTZ001


def test_versions_empty(tmp_path):
    assert LocalLake(tmp_path).versions("x", "y", D) == []


def test_latest_returns_newest_partition_and_version(tmp_path):
    lake = LocalLake(tmp_path)
    assert lake.latest("nse", "bhav") is None
    lake.put("nse", "bhav", date(2026, 1, 5), b"a", url="u", fetched_at=NOW)
    lake.put("nse", "bhav", date(2026, 3, 1), b"b", url="u", fetched_at=NOW)
    m3 = lake.put("nse", "bhav", date(2026, 3, 1), b"c", url="u", fetched_at=NOW)
    assert lake.latest("nse", "bhav") == m3 and m3.version == 2


def test_latest_skips_an_empty_partition_directory(tmp_path):
    lake = LocalLake(tmp_path)
    m = lake.put("nse", "bhav", date(2026, 1, 5), b"a", url="u", fetched_at=NOW)
    (tmp_path / "raw/nse/bhav/dt=2026-02-01").mkdir()  # newer folder with no files in it
    assert lake.latest("nse", "bhav") == m
