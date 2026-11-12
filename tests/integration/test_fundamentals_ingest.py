import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from algo.data.fundamentals_ingest import Blocked, backfill_facts, ingest_symbol
from algo.data.lake import LocalLake
from algo.data.providers.nse_client import NotPublished, NseHttpError
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
DATA = Path(__file__).parents[1] / "data/nse"
NOW = datetime(2026, 11, 10, tzinfo=UTC)
LISTING = (DATA / "results_listing_RELIANCE.json").read_bytes()
XBRL = (DATA / "results_xbrl_RELIANCE_cons.xml").read_bytes()
INTEGRATED = (DATA / "integrated_listing_TCS.json").read_bytes()
TCS_XBRL = (DATA / "integrated_xbrl_TCS_cons_2026q2.xml").read_bytes()


class Fake:
    """An injected `get`: serves the listing and the XBRL files, or raises what it is told to."""

    def __init__(self, listing=LISTING, xbrl=XBRL, raises=None):
        self.listing, self.xbrl, self.raises, self.calls = listing, xbrl, raises or {}, []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        for key, exc in self.raises.items():
            if key in url:
                raise exc
        if "corporates-financial-results" in url:
            return self.listing
        if "integrated-filing-results" in url:
            return INTEGRATED
        if (
            "_1348254_" in url or "_1734606_" in url
        ):  # the standalone filing of the fixture gets a genuine standalone statement
            return self.xbrl.replace(b">Consolidated<", b">Standalone<")
        return self.xbrl


@pytest.fixture
def env(conn, tmp_path):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "RELIANCE", isin="INE002A01018")
    return conn, LocalLake(tmp_path), iid


def counts(conn):
    return {
        t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("fundamental_filing", "fundamental_fact", "fundamental_unloaded")
    }  # noqa: S608


def test_a_symbol_is_loaded_with_raw_files_kept_and_old_format_filings_noted_as_gaps(env):
    conn, lake, iid = env
    r = ingest_symbol(conn, lake, Fake(), "RELIANCE", NOW, since=date(2016, 4, 1))
    # the fixture lists 4 filings: two Dec-2024 (XBRL) and two Dec-2017 (old format, no XBRL)
    assert (r.listed, r.stored, r.already, r.noted) == (4, 2, 0, {"NO_XBRL_OLD_FORMAT": 2})
    assert conn.execute("SELECT instrument_id FROM fundamental_filing").fetchall() == [
        (iid,),
        (iid,),
    ]
    assert counts(conn)["fundamental_filing"] == 2 and counts(conn)["fundamental_unloaded"] == 2
    sha = conn.execute("SELECT raw_sha256 FROM fundamental_filing LIMIT 1").fetchone()[0]
    assert len(sha) == 64 and lake.versions(
        "nse", "financial_results_RELIANCE", NOW.date()
    )  # listing kept untouched
    assert lake.versions(
        "nse", "results_xbrl_RELIANCE", date(2025, 1, 16)
    )  # and each XBRL, under its filing date


def test_a_rerun_fetches_the_listing_but_no_filing_that_is_already_stored(env):
    conn, lake, _ = env
    ingest_symbol(conn, lake, Fake(), "RELIANCE", NOW)
    second = Fake()
    r = ingest_symbol(conn, lake, second, "RELIANCE", NOW)
    assert (r.stored, r.already) == (0, 2) and counts(conn)["fundamental_filing"] == 2
    assert [u for u in second.calls if "xbrl" in u] == []  # nothing re-downloaded


def test_the_period_and_basis_filters_limit_what_is_fetched(env):
    conn, lake, _ = env
    g = Fake()
    r = ingest_symbol(
        conn, lake, g, "RELIANCE", NOW, since=date(2024, 1, 1), bases=("CONSOLIDATED",)
    )
    assert (r.stored, r.noted) == (1, {}) and counts(conn)[
        "fundamental_unloaded"
    ] == 0  # the 2017 rows are out of scope, not gaps
    assert len([u for u in g.calls if "xbrl" in u]) == 1


def test_a_failed_download_or_an_unreadable_file_is_noted_and_the_rest_continue(env):
    conn, lake, _ = env
    g = Fake(raises={"_1348248_": NotPublished(404, "u")})  # the consolidated XBRL is missing
    r = ingest_symbol(conn, lake, g, "RELIANCE", NOW, since=date(2024, 1, 1))
    assert (r.stored, r.noted) == (1, {"FETCH_FAILED": 1})
    assert conn.execute("SELECT seq_number, reason FROM fundamental_unloaded").fetchall() == [
        ("1189821", "FETCH_FAILED")
    ]
    r2 = ingest_symbol(
        conn, lake, Fake(xbrl=b"<html>maintenance</html>"), "RELIANCE", NOW, since=date(2024, 1, 1)
    )
    assert (r2.already, r2.noted) == (
        1,
        {"UNPARSEABLE": 1},
    )  # the stored one is skipped, the other is unreadable
    assert counts(conn)["fundamental_filing"] == 1


def test_a_block_by_the_exchange_stops_the_run_instead_of_hammering(env):
    conn, lake, _ = env
    for status in (401, 403):
        with pytest.raises(Blocked, match=str(status)):
            ingest_symbol(
                conn,
                lake,
                Fake(raises={"corporates-financial-results": NseHttpError(status, "u")}),
                "RELIANCE",
                NOW,
            )
    with pytest.raises(Blocked, match="403"):
        ingest_symbol(
            conn,
            lake,
            Fake(raises={"xbrl": NseHttpError(403, "u")}),
            "RELIANCE",
            NOW,
            since=date(2024, 1, 1),
        )
    assert counts(conn)["fundamental_filing"] == 0


def test_a_listing_that_is_not_a_listing_is_an_error_and_a_symbol_with_no_filings_is_empty(env):
    conn, lake, _ = env
    with pytest.raises(Exception, match="not a results listing"):
        ingest_symbol(conn, lake, Fake(listing=b"<html>denied</html>"), "RELIANCE", NOW)
    r = ingest_symbol(conn, lake, Fake(listing=json.dumps([]).encode()), "RELIANCE", NOW)
    assert (r.listed, r.stored) == (0, 0)


def test_cumulative_filings_are_not_quarters_and_are_noted_rather_than_loaded(env):
    conn, lake, _ = env
    rows = json.loads(LISTING)
    for row in rows:
        row["cumulative"] = "Cumulative"
    r = ingest_symbol(conn, lake, Fake(listing=json.dumps(rows).encode()), "RELIANCE", NOW)
    assert r.stored == 0 and r.noted == {"NOT_QUARTERLY": 4}


def test_a_symbol_the_master_does_not_know_still_loads_without_an_instrument(env):
    conn, lake, _ = env
    rows = json.loads(LISTING)
    for row in rows:
        row["isin"] = "INE000000000"
    r = ingest_symbol(
        conn, lake, Fake(listing=json.dumps(rows).encode()), "RELIANCE", NOW, since=date(2024, 1, 1)
    )
    assert r.stored == 2 and conn.execute(
        "SELECT DISTINCT instrument_id FROM fundamental_filing"
    ).fetchall() == [(None,)]


def test_a_filing_without_an_exact_filing_time_is_counted_as_a_gap_and_never_stored_with_a_guessed_time(
    env,
):
    conn, lake, _ = env
    rows = json.loads(LISTING)
    for row in rows:
        row["broadCastDate"], row["exchdisstime"] = None, None
    g = Fake(listing=json.dumps(rows).encode())
    r = ingest_symbol(conn, lake, g, "RELIANCE", NOW, since=date(2016, 4, 1))
    assert r.stored == 0 and r.noted == {"NO_FILING_TIME": 4}
    assert [u for u in g.calls if "xbrl" in u] == [] and counts(conn)["fundamental_filing"] == 0


def test_a_raw_file_already_in_the_lake_is_reparsed_without_downloading_it_again(env):
    conn, lake, _ = env
    rows = json.loads(LISTING)
    cons = next(
        r for r in rows if r["toDate"] == "31-Dec-2024" and r["consolidated"] == "Consolidated"
    )
    lake.put(
        "nse", "results_xbrl_RELIANCE", date(2025, 1, 16), XBRL, url=cons["xbrl"], fetched_at=NOW
    )  # kept from an earlier run
    g = Fake(raises={"xbrl": NseHttpError(500, "would be a download")})
    r = ingest_symbol(
        conn, lake, g, "RELIANCE", NOW, since=date(2024, 1, 1), bases=("CONSOLIDATED",)
    )
    assert (r.stored, r.noted) == (1, {}) and [u for u in g.calls if "xbrl" in u] == []
    other = Fake(
        raises={"xbrl": NotPublished(404, "u")}
    )  # a different url in the lake is not reused
    lake2 = LocalLake(lake.root / "elsewhere")
    lake2.put(
        "nse",
        "results_xbrl_RELIANCE",
        date(2025, 1, 16),
        XBRL,
        url="https://example.invalid/other.xml",
        fetched_at=NOW,
    )
    conn.execute("DELETE FROM fundamental_fact")
    conn.execute("DELETE FROM fundamental_filing")
    r2 = ingest_symbol(
        conn, lake2, other, "RELIANCE", NOW, since=date(2024, 1, 1), bases=("CONSOLIDATED",)
    )
    assert r2.noted == {"FETCH_FAILED": 1}


def test_a_stale_isin_in_the_listing_falls_back_to_the_symbol_alias_valid_on_the_filing_date(env):
    conn, lake, iid = env
    InstrumentRepo(conn).add_alias(iid, "nse", "RELIANCE", date(2000, 1, 1))
    rows = json.loads(LISTING)
    for row in rows:
        row["isin"] = (
            "INE002A01000"  # not in the master (a pre-split ISIN, as NSE still prints for some companies)
        )
    r = ingest_symbol(
        conn, lake, Fake(listing=json.dumps(rows).encode()), "RELIANCE", NOW, since=date(2024, 1, 1)
    )
    assert r.stored == 2 and conn.execute(
        "SELECT DISTINCT instrument_id FROM fundamental_filing"
    ).fetchall() == [(iid,)]


def test_a_symbol_alias_that_was_not_valid_on_the_filing_date_never_links(env):
    conn, lake, iid = env
    InstrumentRepo(conn).add_alias(
        iid, "nse", "RELIANCE", date(2025, 6, 1)
    )  # starts after the January 2025 filing
    rows = json.loads(LISTING)
    for row in rows:
        row["isin"] = "INE002A01000"
    ingest_symbol(
        conn, lake, Fake(listing=json.dumps(rows).encode()), "RELIANCE", NOW, since=date(2024, 1, 1)
    )
    assert conn.execute("SELECT DISTINCT instrument_id FROM fundamental_filing").fetchall() == [
        (None,)
    ]


def test_integrated_filings_are_loaded_with_isin_from_the_xbrl_and_matched_to_the_instrument(env):
    conn, lake, _ = env
    tcs = InstrumentRepo(conn).add_instrument(
        conn.execute("SELECT min(exchange_id) FROM exchange").fetchone()[0],
        "TCS",
        isin="INE467B01029",
    )
    fake = Fake(xbrl=TCS_XBRL)
    r = ingest_symbol(conn, lake, fake, "TCS", NOW, since=date(2025, 1, 1), integrated=True)
    # the fixture also holds a PAGEIND revision, which the symbol filter drops
    assert (r.listed, r.stored) == (2, 2)
    assert conn.execute(
        "SELECT DISTINCT instrument_id, isin, seq_number LIKE 'IF%%', rounding FROM fundamental_filing"
    ).fetchall() == [(tcs, "INE467B01029", True, "Crores")]
    assert lake.versions("nse", "integrated_filing_TCS", NOW.date())
    again = ingest_symbol(
        conn, lake, Fake(xbrl=TCS_XBRL), "TCS", NOW, since=date(2025, 1, 1), integrated=True
    )
    assert (again.stored, again.already) == (0, 2)


def test_the_whole_filing_is_stored_and_a_backfill_restores_it_for_filings_stored_before(env):
    conn, lake, _ = env
    InstrumentRepo(conn).add_instrument(
        conn.execute("SELECT min(exchange_id) FROM exchange").fetchone()[0],
        "TCS",
        isin="INE467B01029",
    )
    ingest_symbol(
        conn, lake, Fake(xbrl=TCS_XBRL), "TCS", NOW, since=date(2025, 1, 1), integrated=True
    )
    q = "SELECT scope, count(*) FROM fundamental_fact WHERE metric ~ '^[A-Z]' GROUP BY 1 ORDER BY 1"
    full = conn.execute(q).fetchall()
    assert [s for s, _ in full] == ["INSTANT", "QUARTER", "YTD"] and all(n > 20 for _, n in full)
    assert (
        conn.execute(
            "SELECT value FROM fundamental_fact WHERE metric='Assets' AND scope='INSTANT' LIMIT 1"
        ).fetchone()[0]
        == 1907820000000
    )
    conn.execute("DELETE FROM fundamental_fact WHERE metric ~ '^[A-Z]'")
    assert backfill_facts(conn, lake) == 2  # two filings re-read from the lake, no network
    assert conn.execute(q).fetchall() == full
    assert backfill_facts(conn, lake) == 2 and conn.execute(q).fetchall() == full  # idempotent
