# ruff: noqa: E501
from datetime import UTC, date, datetime

import pytest

from algo.backtest.validation import registry
from algo.promotion import verdicts as pv
from algo.research import holdout_batch as hb
from algo.research import holdout_evaluator as ev
from algo.research import holdout_lock, study_jobs, study_store
from algo.research.holdout_lock import Lock
from algo.research.study_runner import run_study
from algo.research.study_store import register_study
from tests.integration.test_study_runner import CHOSEN, LONG, build_env, long_spec, with_report
from tests.support.research_lock import write_lock_file

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
LOCK = Lock(
    LONG[939], LONG[940], LONG[-1]
)  # the study ends the day before the global holdout begins


@pytest.fixture
def world(conn, monkeypatch, tmp_path):
    """A real study: registered inside the development window, its trials run (which seals its dataset), a passed report. The lock is anchored so
    the holdout is the last sessions of the synthetic data."""
    monkeypatch.setattr(
        study_store, "git_state", lambda: ("abc123", False)
    )  # the test tree is not what is being reproduced
    conn, owner = build_env(conn, LONG, date(2020, 6, 30))
    monkeypatch.setattr(holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "lock.json", LOCK))
    holdout_lock.anchor(conn, LOCK, by="owner", reason="test", now=NOW)
    spec = long_spec(end=LONG[939].isoformat(), holdout_start=LONG[800].isoformat())
    sid = register_study(conn, owner, spec, NOW)
    run_study(conn, study_jobs.enqueue(conn, sid, owner, NOW), NOW)
    with_report(conn, sid, passed=True)
    return conn, owner, sid


def frozen(conn, sid):
    bid = hb.register(conn, by="owner", now=NOW)
    m = ev.build_manifest(conn, bid, [sid])
    sha = hb.freeze(conn, bid, m, NOW)
    return bid, hb.Manifest.from_json(
        conn.execute("SELECT manifest FROM holdout_batch WHERE batch_id=%s", (bid,)).fetchone()[0]
    ) if sha else m  # the stored one carries the seeds


def test_the_manifest_is_read_from_the_registry_and_gaps_and_missing_settings_are_refused(world):
    conn, owner, sid = world
    bid = hb.register(conn, by="owner", now=NOW)
    m = ev.build_manifest(conn, bid, [sid])
    (c,) = m.candidates
    family = conn.execute(
        "SELECT family_id FROM experiment WHERE experiment_id=%s", (sid,)
    ).fetchone()[0]
    sealed = conn.execute(
        "SELECT dataset_sha256 FROM study_dataset WHERE experiment_id=%s", (sid,)
    ).fetchone()[0]
    assert c.family_id == str(family) and m.family_trials == {
        str(family): registry.family_trial_count(conn, family)
    }
    assert c.dataset_sha256 == sealed and c.parameter_hash == registry.params_hash(CHOSEN)
    assert (
        c.validation_report_id
        == conn.execute(
            "SELECT report_id FROM validation_report WHERE experiment_id=%s", (sid,)
        ).fetchone()[0]
    )
    assert (m.date_from, m.date_to, m.evaluator_version) == (
        LOCK.holdout_start,
        LOCK.holdout_end,
        hb.EVALUATOR_VERSION,
    )
    # a study that is not ready is refused with every gap named
    other = register_study(
        conn,
        owner,
        long_spec(name="other", end=LONG[939].isoformat(), holdout_start=LONG[800].isoformat()),
        NOW,
    )  # never run, no verdict
    with pytest.raises(hb.BatchError) as e:
        ev.build_manifest(conn, bid, [sid, other, 987654])
    text = str(e.value)
    assert "987654 is not a registered study" in text
    assert (
        f"study {other} has not sealed its dataset" in text
        and f"study {other} has no passed development verdict" in text
    )
    assert f"study {sid} " not in text  # the ready one raises no complaint
    hb.freeze(conn, bid, m, NOW)  # and the batch accepts the good manifest as it is
    # a candidate whose study or chosen settings are missing is a batch error, never a verdict
    ghost = hb.Candidate(
        c.candidate_id,
        c.family_id,
        c.strategy_version,
        c.parameter_hash,
        c.dataset_sha256,
        "no-such-study",
        c.validation_report_id,
    )
    with pytest.raises(hb.BatchError, match="no registered study"):
        ev._candidate(conn, ghost, m, lambda known_at: None)
    conn.execute(
        "UPDATE validation_report SET refs='{}' WHERE report_id=%s", (c.validation_report_id,)
    )
    with pytest.raises(hb.BatchError, match="names no chosen settings"):
        ev._candidate(conn, c, m, lambda known_at: None)


def test_the_evaluator_runs_the_chosen_settings_over_the_holdout_and_consumes_it_once(world):
    conn, _, sid = world
    bid, m = frozen(conn, sid)
    assert conn.execute("SELECT state FROM holdout_batch").fetchone() == ("FROZEN",)
    ev.run_batch(conn, bid, NOW)
    assert conn.execute("SELECT state FROM holdout_batch").fetchone() == ("CONSUMED",)
    rows = pv.read_verdicts(conn)
    assert sorted(g for _, g, _ in rows) == sorted(ev.HOLDOUT_GATES)
    assert {v for _, _, v in rows} <= set(hb.VERDICTS)
    report = conn.execute("SELECT report FROM holdout_report WHERE batch_id=%s", (bid,)).fetchone()[
        0
    ]
    (info,) = report["candidates"].values()
    assert (
        info["chosen"] == CHOSEN
        and info["window"][0] >= LOCK.holdout_start.isoformat()
        and info["window"][1] == LOCK.holdout_end.isoformat()
    )
    assert report["manifest_sha256"] == m.sha256 and report["evaluator"] == hb.EVALUATOR_VERSION
    with pytest.raises(hb.BatchError, match="CONSUMED"):
        ev.run_batch(conn, bid, NOW)  # the holdout is spent: a second look is refused


def test_a_candidate_that_cannot_be_run_gets_insufficient_evidence_on_every_gate_never_a_pass(
    world, monkeypatch
):
    conn, _, sid = world
    bid, _ = frozen(conn, sid)

    class Empty:
        def ever(self):
            return set()

    monkeypatch.setattr(ev.study_universe, "build", lambda *a, **k: (Empty(), []))
    ev.run_batch(conn, bid, NOW)
    rows = pv.read_verdicts(conn)
    assert {v for _, _, v in rows} == {"INSUFFICIENT_EVIDENCE"} and len(rows) == len(
        ev.HOLDOUT_GATES
    )
    assert pv.promotable(conn, rows[0][0]) is False
    report = conn.execute("SELECT report FROM holdout_report").fetchone()[0]
    assert "no stocks to trade" in next(iter(report["candidates"].values()))["error"]


def test_an_equity_curve_that_misses_a_session_of_the_window_is_insufficient_evidence(
    world, monkeypatch
):
    conn, _, sid = world
    bid, _ = frozen(conn, sid)
    real = ev._sessions
    monkeypatch.setattr(
        ev, "_sessions", lambda c, b, e: real(c, b, e) | {date(2026, 11, 13)}
    )  # a session the curve cannot have
    ev.run_batch(conn, bid, NOW)
    rows = pv.read_verdicts(conn)
    assert {v for _, _, v in rows} == {"INSUFFICIENT_EVIDENCE"} and pv.promotable(
        conn, rows[0][0]
    ) is False
    report = conn.execute("SELECT report FROM holdout_report").fetchone()[0]
    assert "misses 1 session" in next(iter(report["candidates"].values()))["error"]
