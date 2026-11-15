# ruff: noqa: E501, F811
"""Fundamental features through the real job and store: the filings are loaded only up to the development end, their identity is part of the dataset identity, and the stored
values follow the point-in-time rule."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D

import pytest

from algo.features import job, store
from algo.features.fundamental import FilingsHistory
from tests.integration.features.test_job import ALL_READY, JAN, NOW, go, world  # noqa: F401

pytestmark = pytest.mark.integration
FEATURE = "fund_revenue_growth"
LAST_DEV_DAY = date(2026, 2, 28)  # the lock in these tests: development ends here


def add_filing(conn, iid, seq, end, filed_day, revenue, pat=10, raw="x", basis="CONSOLIDATED"):
    fid = conn.execute(
        "INSERT INTO fundamental_filing (symbol,isin,instrument_id,seq_number,period_start,period_end,basis,audited,bank,filed_at,rounding,xbrl_url,raw_sha256,ingested_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,false,false,%s,'',%s,%s,%s) RETURNING filing_id",
        (
            f"S{iid}",
            f"INE{iid}",
            iid,
            str(seq),
            end - timedelta(days=90),
            end,
            basis,
            datetime.combine(filed_day, time(16, 30), UTC),
            "u",
            f"{raw}{iid}{seq}",
            NOW,
        ),
    ).fetchone()[0]
    conn.cursor().executemany(
        "INSERT INTO fundamental_fact (filing_id, metric, scope, value) VALUES (%s,%s,'QUARTER',%s)",
        [(fid, "RevenueFromOperations", D(revenue)), (fid, "ProfitLossForPeriod", D(pat))],
    )
    return fid


def five_quarters(conn, iid, last_revenue=120):
    """Sep-24 .. Sep-25, each filed 45 days later: revenue 100 four times then `last_revenue` (a year-on-year rise of last_revenue - 100 percent)."""
    ends = [
        date(2024, 9, 30),
        date(2024, 12, 31),
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
    ]
    for n, end in enumerate(ends):
        add_filing(conn, iid, n, end, end + timedelta(days=45), last_revenue if n == 4 else 100)


@pytest.fixture
def fworld(world):
    conn, ids, fid = world
    store.set_status(conn, FEATURE, "1", "USABLE", by="owner", reason="test", now=NOW)
    return conn, ids, fid


def test_only_filings_made_on_or_before_the_development_end_are_loaded_and_each_company_keeps_its_bases(
    fworld,
):
    conn, ids, _ = fworld
    five_quarters(conn, ids[0])
    add_filing(conn, ids[0], 9, date(2025, 12, 31), date(2026, 2, 14), 130)  # inside development
    add_filing(
        conn, ids[0], 10, date(2026, 3, 31), date(2026, 5, 15), 140
    )  # after the development end: the holdout's filing
    add_filing(conn, ids[1], 0, date(2025, 9, 30), date(2025, 11, 14), 50, basis="STANDALONE")
    got = job.load_filings(conn, ids, LAST_DEV_DAY)
    assert sorted(got) == sorted(ids)
    assert sorted(q.period_end for q in got[ids[0]].filings["CONSOLIDATED"]) == [
        date(2024, 9, 30),
        date(2024, 12, 31),
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
        date(2025, 12, 31),
    ]
    assert list(got[ids[1]].filings) == ["STANDALONE"]
    assert job.load_filings(conn, [ids[1]], date(2025, 11, 13)) == {}  # nothing filed yet by then


def test_the_filings_identity_changes_with_any_filing_and_ignores_the_holdout(fworld):
    conn, ids, _ = fworld
    five_quarters(conn, ids[0])
    base = job.fundamentals_sha256(conn, ids, LAST_DEV_DAY)
    assert base == job.fundamentals_sha256(conn, ids, LAST_DEV_DAY)
    add_filing(conn, ids[0], 10, date(2026, 3, 31), date(2026, 5, 15), 140)  # filed in the holdout
    assert job.fundamentals_sha256(conn, ids, LAST_DEV_DAY) == base  # the holdout changes nothing
    add_filing(conn, ids[0], 9, date(2025, 12, 31), date(2026, 2, 14), 130)
    changed = job.fundamentals_sha256(conn, ids, LAST_DEV_DAY)
    assert changed != base
    conn.execute("UPDATE fundamental_filing SET raw_sha256 = 'different' WHERE seq_number = '9'")
    assert (
        job.fundamentals_sha256(conn, ids, LAST_DEV_DAY) != changed
    )  # even the raw file changing counts


def test_a_price_feature_keeps_the_price_identity_and_a_fundamental_one_adds_the_filings(fworld):
    from algo.features import registry

    conn, ids, fid = fworld
    five_quarters(conn, ids[0])
    price_only = job.feature_dataset_sha256(
        conn, fid, ids, registry.DEFINITIONS["ret_5d"], LAST_DEV_DAY
    )
    assert price_only == job.dataset_sha256(conn, fid, ids)
    fund = job.feature_dataset_sha256(conn, fid, ids, registry.DEFINITIONS[FEATURE], LAST_DEV_DAY)
    assert fund != price_only
    add_filing(conn, ids[0], 9, date(2025, 12, 31), date(2026, 2, 14), 130)
    assert (
        job.feature_dataset_sha256(conn, fid, ids, registry.DEFINITIONS[FEATURE], LAST_DEV_DAY)
        != fund
    )
    assert (
        job.feature_dataset_sha256(conn, fid, ids, registry.DEFINITIONS["ret_5d"], LAST_DEV_DAY)
        == price_only
    )  # prices are untouched


def test_the_job_stores_the_ratio_from_the_session_after_each_filing_and_a_rerun_writes_nothing(
    fworld,
):
    conn, ids, fid = fworld
    five_quarters(
        conn, ids[0]
    )  # filed up to 2025-11-14: June-to-September 2025 shows +20% from then on
    add_filing(
        conn, ids[0], 9, date(2025, 12, 31), date(2026, 2, 13), 130
    )  # Dec 2025 against Dec 2024: +30%, filed Friday 13 Feb
    seen = []
    r = go(conn, fid, progress=lambda phase, msg, **kw: seen.append(phase))
    assert (
        r.status == "complete"
        and (FEATURE, "2026-01") in r.computed
        and (FEATURE, "2026-02") in r.computed
    )
    assert "reading filings" in seen
    rows = conn.execute(
        "SELECT v.instrument_id, v.day, v.value, v.available_at FROM feature_value v JOIN feature_run r USING (run_id) JOIN feature_definition d USING (feature_id) WHERE d.name=%s ORDER BY 1, 2",
        (FEATURE,),
    ).fetchall()
    assert {i for i, *_ in rows} == {ids[0]}  # the company with no filings has no values
    by_day = {d: (v, a) for _, d, v, a in rows}
    assert by_day[date(2026, 1, 5)][0] == D("20.000000000000") and by_day[date(2026, 2, 13)][
        0
    ] == D("20.000000000000")  # still the old figure on the filing day itself
    assert by_day[date(2026, 2, 16)][0] == D("30.000000000000")  # the next session
    assert by_day[date(2026, 2, 16)][1] == datetime(2026, 2, 13, 16, 30, tzinfo=UTC)
    assert max(d for d in by_day) <= LAST_DEV_DAY
    again = go(conn, fid)
    assert again.computed == [] and again.already >= 2
    add_filing(
        conn, ids[0], 11, date(2025, 12, 31), date(2026, 2, 20), 140
    )  # a restatement: a new filing changes the identity, so it is recomputed
    third = go(conn, fid)
    assert (FEATURE, "2026-01") in third.computed and (FEATURE, "2026-02") in third.computed
    later = {
        d: v
        for _, d, v, _ in conn.execute(
            "SELECT v.instrument_id, v.day, v.value, v.available_at FROM feature_value v JOIN feature_run r USING (run_id) JOIN feature_definition d USING (feature_id) WHERE d.name=%s AND r.dataset_sha256 = (SELECT dataset_sha256 FROM feature_run ORDER BY run_id DESC LIMIT 1)",
            (FEATURE,),
        ).fetchall()
    }
    assert later[date(2026, 2, 23)] == D(
        "40.000000000000"
    )  # 140 against 100, from the day after the restatement


def test_without_any_filing_a_fundamental_feature_has_no_rows_but_the_run_is_complete(fworld):
    conn, ids, fid = fworld
    r = go(conn, fid)
    assert (FEATURE, "2026-01") in r.computed
    assert conn.execute(
        "SELECT count(*) FROM feature_value v JOIN feature_run r USING (run_id) JOIN feature_definition d USING (feature_id) WHERE d.name=%s",
        (FEATURE,),
    ).fetchone() == (0,)
    assert FilingsHistory({}).events == []


def test_validation_reads_the_filings_twice_checks_the_cuts_and_reports_under_the_features_own_identity(
    fworld,
):
    from algo.features import registry, validation

    conn, ids, fid = fworld
    five_quarters(conn, ids[0])
    add_filing(conn, ids[0], 9, date(2025, 12, 31), date(2026, 2, 13), 130)
    seen = []
    r = validation.validate(
        conn,
        FEATURE,
        "1",
        fid,
        JAN,
        min_coverage=D("0.4"),
        report=lambda phase, msg: seen.append((phase, msg)),
    )
    assert r["passed"] is True and r["reasons"] == [] and r["family"] == "fundamental"
    assert (
        r["recompute"]["identical"] is True
        and r["lookahead"]["violations"] == 0
        and r["lookahead"]["checks"] > 0
    )
    assert r["dataset_sha256"] == job.feature_dataset_sha256(
        conn, fid, ids, registry.DEFINITIONS[FEATURE], LAST_DEV_DAY
    )
    assert [p for p, _ in seen if p == "reading filings"] == [
        "reading filings",
        "reading filings",
    ]  # two independent reads
    assert 0.4 < float(r["coverage"]["share"]) < 0.6  # one company of two has filings


def test_validation_with_shared_filing_reads_gives_the_same_report_and_reads_nothing_again(
    fworld, monkeypatch
):
    from algo.features import validation

    conn, ids, fid = fworld
    five_quarters(conn, ids[0])
    alone = validation.validate(conn, FEATURE, "1", fid, JAN, min_coverage=D("0.4"))
    reads = []
    real = job.load_filings
    monkeypatch.setattr(job, "load_filings", lambda *a, **k: reads.append(1) or real(*a, **k))
    shared_reads = validation.read_filings(conn, fid, JAN)
    assert len(reads) == 2
    shared = validation.validate(
        conn, FEATURE, "1", fid, JAN, min_coverage=D("0.4"), filings_reads=shared_reads
    )
    assert len(reads) == 2 and shared == alone


def test_a_price_feature_is_validated_without_ever_reading_filings(fworld, monkeypatch):
    from algo.features import validation

    conn, ids, fid = fworld
    monkeypatch.setattr(
        job, "load_filings", lambda *a, **k: pytest.fail("a price feature must not read filings")
    )
    r = validation.validate(conn, "ret_5d", "1", fid, JAN)
    assert r["passed"] and r["family"] == "price"


def test_a_passing_fundamental_feature_becomes_usable_and_alpha_discovery_reads_it_back_under_its_own_identity(
    fworld,
):
    from algo.alpha import run
    from algo.features import validation

    conn, ids, fid = fworld
    five_quarters(conn, ids[0])
    r = validation.validate(conn, FEATURE, "1", fid, JAN, min_coverage=D("0.4"))
    validation.record(conn, FEATURE, "1", r["dataset_sha256"], r, by="test", now=NOW)
    assert store.status(conn, FEATURE, "1") == "USABLE"
    go(conn, fid)  # materialise the usable features for the development months
    evidence = run.measure(conn, fid, JAN, horizons=(1,), min_names=1)
    assert {e.feature for e in evidence} == {"ret_5d", "ret_20d", FEATURE}
    sha = run.batch_dataset_sha256(conn, fid, ids, LAST_DEV_DAY)
    assert sha not in (
        job.dataset_sha256(conn, fid, ids),
    )  # the filings are part of what this batch rests on
    got = run.run_discovery(conn, fid, JAN, NOW, horizons=(1,), min_names=1)
    assert len(got) == 3
    assert {
        r[0] for r in conn.execute("SELECT dataset_sha256 FROM alpha_hypothesis").fetchall()
    } == {sha}
