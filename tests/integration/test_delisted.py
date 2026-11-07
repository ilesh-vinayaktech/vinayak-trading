from datetime import date

import pytest
from psycopg.types.json import Jsonb

from algo.data.delisted import (
    ALIAS_GAP,
    CREATE,
    NEEDS_EVIDENCE,
    STILL_TRADING,
    SUCCESSOR,
    create_instruments,
    data_end,
    load_symbols,
    partitions_to_reload,
    plan,
)  # fmt: skip
from algo.data.index_releases import remap
from algo.data.pipeline import run_partition
from tests.integration.test_pipeline import D0, NOW, Prov, env  # noqa: F401
from tests.support.bt import make_env

pytestmark = pytest.mark.integration
END = date(2026, 11, 5)


def part(conn, d, unknown, status="loaded"):
    conn.execute(
        "INSERT INTO partition_load (source,dataset,partition,raw_version,checksum,status,"
        "dataset_version,detail,at) VALUES ('nse','bhav',%s,1,'c',%s,1,%s,now())",
        (d, status, Jsonb({"unknown_symbols": unknown})),
    )


def row(conn, doc, symbol, eff, component="NIFTY_NEXT_50", company=""):
    conn.execute(
        "INSERT INTO index_release_document VALUES (%s,'1',%s,'u','h','REPLACEMENT_TABLES','[]','[]',now())"
        " ON CONFLICT DO NOTHING",
        (doc, eff),
    )
    conn.execute(
        "INSERT INTO index_release_row (doc_id,parser_version,page,section_no,section_name,component,"
        "action,symbol,company,effective_from,raw_text,mapping_status) VALUES (%s,'1',1,1,'x',%s,"
        "'EXCLUDED',%s,%s,%s,'r','UNMAPPED_SYMBOL')",
        (doc, component, symbol, company, eff),
    )


def scenario(conn):
    make_env(conn)
    a = conn.execute("SELECT instrument_id FROM instrument LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO instrument_alias VALUES (%s,'nse','NESTLE2',NULL,'2023-08-01',NULL)", (a,)
    )
    for d, unk in ((date(2019, 10, 1), ["GONE", "LIVE", "NESTLE2"]), (date(2020, 3, 19), ["GONE"]),
                   (END, ["LIVE"])):  # fmt: skip
        part(conn, d, unk)
    part(conn, date(2021, 1, 1), ["NOPE"], status="quarantined")  # never counts
    row(conn, "d1", "GONE", date(2019, 3, 29))
    row(conn, "d2", "LIVE", date(2020, 1, 1))
    row(conn, "d3", "PRECOV", date(2017, 3, 31))
    row(conn, "d4", "NESTLE2", date(2019, 3, 29))
    row(conn, "d5", "NOPE", date(2021, 1, 1), component=None)  # not a component: not chased
    return a


def test_the_plan_creates_only_what_the_evidence_supports(conn):
    scenario(conn)
    assert data_end(conn) == END
    got = {c.symbol: c for c in plan(conn)}
    assert set(got) == {"GONE", "LIVE", "PRECOV", "NESTLE2"}
    assert got["GONE"].action == CREATE and got["GONE"].last_traded == date(2020, 3, 19)
    assert got["GONE"].first_evidence == date(2019, 3, 29)  # earliest of release / bhavcopy
    assert got["LIVE"].action == STILL_TRADING  # in the data to the end: not a delisting
    assert got["PRECOV"].action == NEEDS_EVIDENCE and got["PRECOV"].last_traded is None
    assert got["NESTLE2"].action == ALIAS_GAP  # never a duplicate of an existing company


def test_creating_instruments_records_the_basis_and_closes_the_alias(conn):
    scenario(conn)
    ids = create_instruments(conn, plan(conn))
    assert set(ids) == {"GONE"}  # only CREATE candidates
    inst = conn.execute(
        "SELECT status, delisted_on, asset_class, meta->>'verified', meta->>'delisting_basis',"
        " meta->>'last_traded_seen' FROM instrument WHERE instrument_id=%s",
        (ids["GONE"],),
    ).fetchone()
    assert inst[:4] == ("delisted", date(2020, 3, 20), "equity", "false")
    assert "inferred" in inst[4] and inst[5] == "2020-03-19"
    alias = conn.execute(
        "SELECT valid_from, valid_to FROM instrument_alias WHERE source_symbol='GONE'"
    ).fetchone()
    assert alias == (date(2019, 3, 29), date(2020, 3, 20))


def test_release_rows_are_remapped_once_the_instrument_exists_and_the_plan_then_skips_it(conn):
    scenario(conn)
    ids = create_instruments(conn, plan(conn))
    assert remap(conn) == 1
    r = conn.execute(
        "SELECT instrument_id, mapping_status FROM index_release_row WHERE symbol='GONE'"
    ).fetchone()
    assert r == (ids["GONE"], "MAPPED") and remap(conn) == 0
    assert "GONE" not in {c.symbol for c in plan(conn)}  # re-running is safe


def test_data_end_needs_loaded_partitions(conn):
    make_env(conn)
    with pytest.raises(ValueError, match="no bhavcopy partitions loaded"):
        data_end(conn)


def test_creating_requires_the_nse_exchange(conn):
    scenario(conn)
    cands = plan(conn)
    conn.execute("DELETE FROM instrument_alias")
    conn.execute("DELETE FROM instrument")
    conn.execute("DELETE FROM exchange")
    with pytest.raises(ValueError, match="NSE exchange not set up"):
        create_instruments(conn, cands)


def test_bars_for_a_newly_known_symbol_load_from_the_stored_file_into_the_same_version(env):  # noqa: F811
    conn, lake, prov, ids = env
    run_partition(conn, lake, prov, "bhav", D0, NOW)  # AGSTRA is not in the master: dropped
    assert conn.execute("SELECT count(*) FROM bar_1d").fetchone()[0] == 4
    assert partitions_to_reload(conn, {"AGSTRA"}) == [D0]
    ex = conn.execute("SELECT exchange_id FROM exchange").fetchone()[0]
    iid = conn.execute(
        "INSERT INTO instrument (asset_class,exchange_id,symbol,quote_currency) VALUES"
        " ('equity',%s,'AGSTRA','INR') RETURNING instrument_id", (ex,)
    ).fetchone()[0]  # fmt: skip
    conn.execute(
        "INSERT INTO instrument_alias VALUES (%s,'nse','AGSTRA',NULL,'2020-01-01',NULL)", (iid,)
    )
    assert load_symbols(conn, lake, D0, {"AGSTRA"}, NOW) == 1
    assert load_symbols(conn, lake, D0, {"AGSTRA"}, NOW) == 0  # idempotent
    v = conn.execute(
        "SELECT dataset_version, source FROM bar_1d WHERE instrument_id=%s", (iid,)
    ).fetchone()
    assert v == (1, "nse")
    assert conn.execute("SELECT count(*) FROM bar_1d").fetchone()[0] == 5  # others untouched
    assert load_symbols(conn, lake, date(2020, 1, 1), {"AGSTRA"}, NOW) == 0  # a day never loaded


def test_a_similarly_named_instrument_starting_soon_after_means_rename_not_delisting(conn):
    make_env(conn)
    ex = conn.execute("SELECT exchange_id FROM exchange").fetchone()[0]
    new = conn.execute(
        "INSERT INTO instrument (asset_class,exchange_id,symbol,quote_currency,name) VALUES"
        " ('equity',%s,'PIRAMALFIN','INR','Piramal Finance Limited') RETURNING instrument_id", (ex,)
    ).fetchone()[0]  # fmt: skip
    conn.execute(
        "INSERT INTO instrument_alias VALUES (%s,'nse','PIRAMALFIN',NULL,'2025-11-07',NULL)", (new,)
    )
    other = conn.execute(
        "INSERT INTO instrument (asset_class,exchange_id,symbol,quote_currency,name) VALUES"
        " ('equity',%s,'LTIM','INR','LTM Limited') RETURNING instrument_id", (ex,)
    ).fetchone()[0]  # fmt: skip
    conn.execute(
        "INSERT INTO instrument_alias VALUES (%s,'nse','LTIM',NULL,'2022-12-05',NULL)", (other,)
    )
    for d, unk in ((date(2019, 10, 1), ["PEL", "MINDTREE", "XY"]), (date(2025, 9, 22), ["PEL"]),
                   (date(2022, 11, 22), ["MINDTREE"]), (date(2026, 11, 5), [])):  # fmt: skip
        part(conn, d, unk)
    row(conn, "p1", "PEL", date(2019, 3, 29), company="Piramal Enterprises Ltd.")
    row(
        conn, "p2", "MINDTREE", date(2019, 3, 29), company="Mindtree Ltd."
    )  # LTIM is a different name
    row(conn, "p3", "XY", date(2019, 3, 29), company="XY")  # first word too short to compare
    got = {c.symbol: c for c in plan(conn)}
    assert got["PEL"].action == SUCCESSOR and "PIRAMALFIN" in got["PEL"].reason
    assert got["MINDTREE"].action == CREATE  # an unrelated name starting nearby does not block it
    assert got["PEL"].company == "Piramal Enterprises Ltd."
    assert set(create_instruments(conn, list(got.values()))) == {"MINDTREE", "XY"}
