from datetime import date
from decimal import Decimal as D

import psycopg
import pytest

from algo.data.benchmark import (
    BenchmarkError,
    dataset_hash,
    gate_returns,
    ingest,
    levels,
    references,
    register,
)  # fmt: skip
from tests.support.bt import NOW

pytestmark = pytest.mark.integration
DAYS = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
ROWS = [(DAYS[0], D(100)), (DAYS[1], D("110.5")), (DAYS[2], D(99))]


@pytest.fixture
def bm(conn):
    from tests.support.bt import make_env

    make_env(conn)  # applies the migrations
    return register(conn, name="Nifty 200 TRI", provider="NSE Indices", index_symbol="NIFTY 200",
                    return_type="TOTAL_RETURN", methodology_version="2024")  # fmt: skip


def put(conn, bid, rows=ROWS):
    return ingest(
        conn, bid, rows, source="niftyindices", source_timestamp=NOW, raw_hash="h1", now=NOW
    )


def test_ingest_stores_levels_and_is_idempotent_for_identical_values(conn, bm):
    assert put(conn, bm) == 3 and put(conn, bm) == 0
    assert levels(conn, bm) == dict(ROWS)
    assert levels(conn, bm, DAYS[1], DAYS[1]) == {DAYS[1]: D("110.5")}
    extra = put(conn, bm, ROWS + [(date(2024, 1, 4), D(101))])
    assert extra == 1


def test_a_changed_value_or_bad_batch_is_rejected_and_nothing_is_stored(conn, bm):
    put(conn, bm)
    with pytest.raises(BenchmarkError, match=r"1 stored value\(s\) differ"):
        put(conn, bm, [(DAYS[0], D(101)), (date(2024, 1, 9), D(5))])
    assert len(levels(conn, bm)) == 3  # the new row in the rejected batch was not stored
    with pytest.raises(BenchmarkError, match="duplicate dates"):
        put(conn, bm, [(DAYS[0], D(1)), (DAYS[0], D(1))])
    with pytest.raises(BenchmarkError, match="positive"):
        put(conn, bm, [(date(2024, 2, 1), D(0))])


def test_stored_observations_cannot_be_updated_or_deleted(conn, bm):
    put(conn, bm)
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        conn.execute("UPDATE benchmark_observation SET close_value = 1")
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        conn.execute("DELETE FROM benchmark_observation")


def test_registration_validates_the_type_and_keeps_series_distinct(conn, bm):
    with pytest.raises(BenchmarkError, match="return_type must be one of"):
        register(
            conn,
            name="x",
            provider="p",
            index_symbol="S",
            return_type="TRI",
            methodology_version="1",
        )
    price = register(conn, name="Nifty 200", provider="NSE Indices", index_symbol="NIFTY 200",
                     return_type="PRICE", methodology_version="2024")  # fmt: skip
    assert price != bm
    with pytest.raises(psycopg.errors.UniqueViolation):
        register(conn, name="dup", provider="p", index_symbol="NIFTY 200", return_type="PRICE",
                 methodology_version="2024")  # fmt: skip


def test_gate_returns_need_a_total_return_series_with_every_date(conn, bm):
    put(conn, bm)
    assert gate_returns(conn, bm, DAYS) == pytest.approx([0.105, 99 / 110.5 - 1])
    price = register(conn, name="p", provider="p", index_symbol="NIFTY 200", return_type="PRICE",
                     methodology_version="2025")  # fmt: skip
    put(conn, price)
    with pytest.raises(BenchmarkError, match="PRICE series cannot back a gate"):
        gate_returns(conn, price, DAYS)
    with pytest.raises(BenchmarkError, match="no level for"):
        gate_returns(conn, bm, [DAYS[0], date(2024, 1, 5)])


def test_the_dataset_hash_and_references_pin_exactly_what_was_used(conn, bm):
    assert references(conn, bm)["observations"] == 0 and references(conn, bm)["first"] is None
    put(conn, bm)
    h = dataset_hash(conn, bm)
    ref = references(conn, bm)
    assert ref["dataset_hash"] == h and ref["return_type"] == "TOTAL_RETURN"
    assert (ref["first"], ref["last"], ref["observations"]) == ("2024-01-01", "2024-01-03", 3)
    put(conn, bm, ROWS + [(date(2024, 1, 4), D(101))])
    assert dataset_hash(conn, bm) != h
    with pytest.raises(BenchmarkError, match="no benchmark 999"):
        references(conn, 999)
