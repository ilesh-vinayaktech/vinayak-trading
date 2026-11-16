# ruff: noqa: E501
from datetime import UTC, datetime

import psycopg
import pytest

from algo.alpha import registry
from algo.alpha.discover import Evidence
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
DS = "d" * 64


def ev(name="ret_5d", horizon=5, mean=0.05, p=0.0001, days=500, version="1"):
    return Evidence(name, version, horizon, days, 150.0, mean, 0.1, mean / 0.1, 0.6, 4.0, p)


def rows(conn):
    return conn.execute(
        "SELECT batch_id, feature_name, horizon_days, research_status, validation_status FROM alpha_hypothesis ORDER BY hypothesis_id"
    ).fetchall()


def test_a_strong_result_is_a_candidate_pending_validation_and_a_weak_or_untestable_one_is_rejected_and_kept(
    conn,
):
    migrate(conn)
    batch = [
        ev("strong", p=1e-9),
        ev("weak", mean=0.005, p=1e-9),
        ev("insignificant", p=0.2),
        ev("negative", mean=-0.06, p=1e-9),
    ]
    batch.append(Evidence("untestable", "1", 5, 3, 10.0, None, None, None, None, None, None))
    ids = registry.record(conn, batch, DS, NOW)
    assert len(ids) == 5
    assert rows(conn) == [
        (1, "strong", 5, "CANDIDATE", "PENDING"),
        (1, "weak", 5, "REJECTED", "NOT_APPLICABLE"),  # |IC| below the minimum
        (1, "insignificant", 5, "REJECTED", "NOT_APPLICABLE"),
        (
            1,
            "negative",
            5,
            "CANDIDATE",
            "PENDING",
        ),  # a stable negative relationship is a relationship (used inverted)
        (1, "untestable", 5, "REJECTED", "NOT_APPLICABLE"),
    ]


def test_the_evidence_records_what_was_measured_the_correction_and_the_direction(conn):
    migrate(conn)
    (hid,) = registry.record(conn, [ev("neg", mean=-0.06, p=1e-9)], DS, NOW)
    e, h, method, ds = conn.execute(
        "SELECT evidence, evidence_sha256, method, dataset_sha256 FROM alpha_hypothesis WHERE hypothesis_id=%s",
        (hid,),
    ).fetchone()
    assert method == "RANK_IC" and ds == DS and len(h) == 64
    assert (
        e["direction"] == "NEGATIVE"
        and e["mean_ic"] == -0.06
        and e["sample_days"] == 500
        and e["avg_names"] == 150.0
    )
    assert (
        e["tests_ever_run"] == 1
        and e["p_value"] == 1e-9
        and e["p_adjusted"] == pytest.approx(1e-9)
        and e["alpha"] == 0.05
        and e["min_abs_ic"] == 0.02
    )


def test_every_hypothesis_ever_tested_raises_the_bar_for_the_next_batch(conn):
    migrate(conn)
    registry.record(
        conn, [ev(f"f{i}", p=0.9) for i in range(40)], DS, NOW
    )  # forty failures on the books
    (hid,) = registry.record(
        conn, [ev("later", p=0.002)], DS, NOW
    )  # 0.002 x 41 tests = 0.082: no longer significant
    status, e = conn.execute(
        "SELECT research_status, evidence FROM alpha_hypothesis WHERE hypothesis_id=%s", (hid,)
    ).fetchone()
    assert (
        status == "REJECTED"
        and e["tests_ever_run"] == 41
        and e["p_adjusted"] == pytest.approx(0.082)
    )
    assert {r[0] for r in rows(conn)} == {1, 2} and registry.tests_ever_run(conn) == 41


def test_a_hypothesis_is_never_changed_or_removed_and_one_batch_cannot_test_the_same_thing_twice(
    conn,
):
    migrate(conn)
    registry.record(conn, [ev()], DS, NOW)
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        conn.execute("UPDATE alpha_hypothesis SET research_status='CANDIDATE'")
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        conn.execute("DELETE FROM alpha_hypothesis")
    with pytest.raises(ValueError, match="more than once"):
        registry.record(
            conn, [ev(), ev()], DS, NOW
        )  # the same feature, version and horizon twice in one batch
    assert len(rows(conn)) == 1


def test_an_empty_batch_is_refused_and_a_naive_time_is_too(conn):
    migrate(conn)
    with pytest.raises(ValueError, match="nothing to record"):
        registry.record(conn, [], DS, NOW)
    with pytest.raises(ValueError):
        registry.record(conn, [ev()], DS, datetime(2026, 11, 15, 12, 0))  # noqa: DTZ001
    assert registry.tests_ever_run(conn) == 0


def test_what_the_caller_says_about_the_data_is_stored_with_the_evidence(conn):
    migrate(conn)
    (hid,) = registry.record(
        conn,
        [ev()],
        DS,
        NOW,
        context={"universe": "freeze instruments; membership not point-in-time"},
    )
    (e,) = conn.execute(
        "SELECT evidence FROM alpha_hypothesis WHERE hypothesis_id=%s", (hid,)
    ).fetchone()
    assert e["context"] == {"universe": "freeze instruments; membership not point-in-time"}
    (hid2,) = registry.record(conn, [ev("other")], DS, NOW)
    assert conn.execute(
        "SELECT evidence->'context' FROM alpha_hypothesis WHERE hypothesis_id=%s", (hid2,)
    ).fetchone() == ({},)


def test_a_zero_mean_ic_has_no_direction_not_a_negative_one(conn):
    migrate(conn)
    registry.record(
        conn, [ev("a", mean=0.0, p=0.9), ev("b", mean=-0.05), ev("c", mean=0.05)], "d" * 64, NOW
    )
    got = dict(
        conn.execute("SELECT feature_name, evidence->>'direction' FROM alpha_hypothesis").fetchall()
    )
    assert got == {"a": None, "b": "NEGATIVE", "c": "POSITIVE"}


def test_the_default_correction_is_a_false_discovery_rate_over_every_test_ever_run_and_says_so(
    conn,
):
    """Review 2026-11-16, section 3.5: Bonferroni over all tests treats one feature at four horizons as four independent tries."""
    migrate(conn)
    registry.record(
        conn, [ev(f"f{i}", p=0.9) for i in range(40)], DS, NOW
    )  # forty failures on the books
    (hid,) = registry.record(conn, [ev("later", p=0.002)], DS, NOW)
    status, e = conn.execute(
        "SELECT research_status, evidence FROM alpha_hypothesis WHERE hypothesis_id=%s", (hid,)
    ).fetchone()
    assert (
        e["correction"] == "benjamini_hochberg_over_all_tests_ever_run"
        and e["tests_ever_run"] == 41
    )
    assert e["p_adjusted"] == pytest.approx(
        0.002 * 41 / 1
    )  # the smallest of 41 p-values: 0.002 x 41 / rank 1 = 0.082
    assert status == "REJECTED"  # 0.082 is still above 0.05: the tests ever run still raise the bar


def test_a_strong_result_among_weak_ones_passes_under_bh_where_bonferroni_would_not(conn):
    migrate(conn)
    p = [0.00005, 0.00009, 0.0001, 0.0002] + [0.9] * 40  # four real effects among 44 tests
    ids = registry.record(conn, [ev(f"f{i}", p=v) for i, v in enumerate(p)], DS, NOW)
    status = dict(
        conn.execute("SELECT hypothesis_id, research_status FROM alpha_hypothesis").fetchall()
    )
    assert [status[i] for i in ids[:4]] == ["CANDIDATE"] * 4  # q = 0.0022, 0.0022, 0.0022, 0.0044
    other = registry.record(conn, [ev("g", p=0.00005)], DS, NOW, correction="bonferroni")[0]
    assert conn.execute(
        "SELECT evidence->>'correction' FROM alpha_hypothesis WHERE hypothesis_id=%s", (other,)
    ).fetchone() == ("bonferroni_over_all_tests_ever_run",)
