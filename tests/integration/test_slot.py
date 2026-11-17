# ruff: noqa: E501
import re
import subprocess
import sys
import textwrap
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from algo.research import slot

pytestmark = pytest.mark.integration


def test_the_slot_is_exclusive_across_connections_and_free_again_after_release(conn, pg_url):
    with slot.hold(conn, "first"):
        with psycopg.connect(pg_url, autocommit=True) as other:
            with pytest.raises(slot.SlotTimeout, match="first"):
                with slot.hold(other, "second", timeout_s=0.3, poll_s=0.05):
                    pytest.fail("two research jobs held the slot together")
    with psycopg.connect(pg_url, autocommit=True) as other, slot.hold(other, "second", timeout_s=1):
        pass  # released on exit: the next one gets it at once


def test_the_slot_is_released_when_the_job_dies_with_an_exception(conn, pg_url):
    with pytest.raises(RuntimeError):
        with slot.hold(conn, "crashing"):
            raise RuntimeError("boom")
    with psycopg.connect(pg_url, autocommit=True) as other, slot.hold(other, "next", timeout_s=1):
        pass


def test_taking_the_slot_twice_on_one_connection_is_refused_not_silently_nested(conn):
    with slot.hold(conn, "outer"):
        with pytest.raises(slot.SlotTimeout, match="already hold"):
            with slot.hold(conn, "inner"):
                pass


def test_a_waiter_gets_the_slot_the_moment_the_holder_lets_go(conn, pg_url):
    got: list[float] = []

    def waiter():
        with (
            psycopg.connect(pg_url, autocommit=True) as other,
            slot.hold(other, "waiter", timeout_s=5, poll_s=0.05),
        ):
            got.append(time.monotonic())

    with slot.hold(conn, "holder"):
        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.3)
        assert got == []  # still waiting
        released = time.monotonic()
    t.join(5)
    assert got and got[0] >= released


def test_two_processes_started_together_run_one_after_the_other(pg_url):
    """Real processes, real connections: each holds the slot for 0.6 s and records when; the two intervals must not overlap."""
    code = textwrap.dedent(
        """
        import sys, time, psycopg
        from algo.research import slot
        with psycopg.connect(sys.argv[1], autocommit=True) as c, slot.hold(c, "p" + sys.argv[2], timeout_s=20, poll_s=0.05):
            start = time.time(); time.sleep(0.6); print(start, time.time())
        """
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, pg_url, str(i)], stdout=subprocess.PIPE, text=True
        )
        for i in range(2)
    ]
    spans = sorted(tuple(map(float, p.communicate(timeout=60)[0].split())) for p in procs)
    assert all(p.returncode == 0 for p in procs)
    assert spans[0][1] <= spans[1][0]


def test_busy_reason_on_an_injected_clock_and_process_list():
    mon_10am = datetime(2026, 11, 16, 4, 30, tzinfo=UTC)  # 10:00 IST on a Monday
    night = datetime(2026, 11, 16, 17, 0, tzinfo=UTC)
    assert slot.busy_reason(mon_10am, []) == "market hours"
    assert (
        slot.busy_reason(night, ["uv run python scripts/run_paper.py"]) == "run_paper.py is running"
    )
    assert (
        slot.busy_reason(night, ["python scripts/paper_orders.py"]) == "paper_orders.py is running"
    )
    assert slot.busy_reason(night, ["unrelated"]) is None


ROOT = Path(__file__).parents[2]
# what makes a script a research entry point: it runs a backtest, a study, the holdout evaluation or the feature job
RESEARCH = re.compile(
    r"\b(run_backtest|run_study|study_runner|holdout_evaluator|features import [^\n]*\b(?:job|validation)\b|materialise_month|alpha import [^\n]*\brun\b)\b"
)


def test_every_script_that_runs_research_takes_the_slot():
    """The static scan of docs/vti-phase1-spec.md item G. It is not the only proof (two real processes above), but a new script that forgets the
    slot fails here."""
    missing = []
    found = []
    for p in sorted((ROOT / "scripts").glob("*.py")):
        text = p.read_text()
        if RESEARCH.search(text):
            found.append(p.name)
            if "slot.hold(" not in text:
                missing.append(p.name)
    assert found, "the scan found no research scripts: its pattern is wrong"
    assert missing == [], f"these research scripts do not take algo.research.slot.hold: {missing}"


def test_nice_lowers_priority_and_a_non_autocommit_connection_is_refused(conn, pg_url, monkeypatch):
    calls = []
    monkeypatch.setattr(slot.os, "nice", lambda n: calls.append(n))
    with slot.hold(conn, "niced", nice=10):
        pass
    assert calls == [10]
    with psycopg.connect(pg_url) as manual:  # autocommit off
        with pytest.raises(ValueError, match="autocommit"):
            with slot.hold(manual, "x"):
                pass


def test_study_runs_can_share_several_slots_while_other_jobs_still_take_turns(conn, pg_url):
    with (
        psycopg.connect(pg_url, autocommit=True) as b,
        psycopg.connect(pg_url, autocommit=True) as c,
        psycopg.connect(pg_url, autocommit=True) as d,
    ):
        with slot.hold(conn, "study 1", slots=2), slot.hold(b, "study 2", slots=2):
            with pytest.raises(slot.SlotTimeout):  # a third study finds both taken
                with slot.hold(c, "study 3", slots=2, timeout_s=0.3, poll_s=0.05):
                    pytest.fail("three studies held two slots")
            with pytest.raises(
                slot.SlotTimeout
            ):  # and any other job (one slot) still waits for the first
                with slot.hold(d, "feature job", timeout_s=0.3, poll_s=0.05):
                    pytest.fail("a single-slot job ran beside two studies")
        with slot.hold(c, "study 3", slots=2, timeout_s=1):
            pass  # both released: free again
