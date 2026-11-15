from datetime import UTC, datetime, timedelta

from algo.live.heartbeat import (
    DEFAULT_EXPECTED,
    Beat,
    Expectation,
    assess,
    expected_from_env,
    from_feed_status,
)

NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # 10:30 IST, a trading morning
FEED = Expectation("feed", timedelta(seconds=120), session_only=True)
WORKER = Expectation("study_worker", timedelta(seconds=300), session_only=False)


def beat(process="feed", state="RUNNING", ago=10):
    return Beat(process, state, "", NOW - timedelta(seconds=ago))


def test_a_fresh_running_process_is_fine_and_a_missing_one_is_named():
    assert assess({"feed": beat()}, [FEED], NOW, in_session=True) == []
    assert assess({}, [FEED], NOW, in_session=True) == ["feed has never reported"]


def test_a_process_silent_beyond_its_limit_is_a_missed_heartbeat_with_its_age():
    (problem,) = assess({"feed": beat(ago=121)}, [FEED], NOW, in_session=True)
    assert "feed" in problem and "121 s" in problem and "120 s" in problem
    assert (
        assess({"feed": beat(ago=120)}, [FEED], NOW, in_session=True) == []
    )  # the limit itself is allowed


def test_a_degraded_process_is_reported_even_while_it_beats():
    (problem,) = assess(
        {"feed": Beat("feed", "DEGRADED", "reconnecting", NOW)}, [FEED], NOW, in_session=True
    )
    assert "DEGRADED" in problem and "reconnecting" in problem


def test_stopped_is_a_problem_only_while_the_process_is_expected_to_be_running():
    stopped = {"feed": beat(state="STOPPED", ago=5)}
    assert (
        assess(stopped, [FEED], NOW, in_session=False) == []
    )  # the feed ends with the session, on purpose
    assert "STOPPED" in assess(stopped, [FEED], NOW, in_session=True)[0]


def test_a_session_only_process_is_ignored_outside_the_session_but_an_always_expected_one_is_not():
    assert assess({}, [FEED], NOW, in_session=False) == []
    assert assess({"feed": beat(ago=9999)}, [FEED], NOW, in_session=False) == []
    assert assess({}, [WORKER], NOW, in_session=False) == ["study_worker has never reported"]


def test_the_feeds_own_status_row_is_read_as_its_heartbeat():
    row = {"state": "CONNECTED", "detail": "ok", "updated_at": NOW}
    assert from_feed_status(row) == Beat("feed", "RUNNING", "ok", NOW)
    for feed, mapped in (
        ("STARTING", "STARTING"),
        ("RECONNECTING", "DEGRADED"),
        ("TOKEN_EXPIRED", "DEGRADED"),
        ("STOPPED", "STOPPED"),
    ):
        assert from_feed_status({**row, "state": feed}).state == mapped
    assert from_feed_status(None) is None


def test_which_processes_are_expected_comes_from_the_environment_and_defaults_to_the_feed_only():
    assert [e.process for e in expected_from_env({})] == ["feed"]
    assert [
        e.process for e in expected_from_env({"ALGO_EXPECT_PROCESSES": "feed, study_worker"})
    ] == ["feed", "study_worker"]
    assert expected_from_env({"ALGO_EXPECT_PROCESSES": ""}) == []
    import pytest

    with pytest.raises(ValueError, match="unknown process"):
        expected_from_env({"ALGO_EXPECT_PROCESSES": "feed,nope"})
    assert set(DEFAULT_EXPECTED) == {"feed", "study_worker"}


def test_a_beat_dated_ahead_of_this_clock_is_clock_skew_and_a_small_difference_is_tolerated():
    ahead = {"feed": Beat("feed", "RUNNING", "", NOW + timedelta(minutes=10))}
    (problem,) = assess(ahead, [FEED], NOW, in_session=True)
    assert "600 s ahead of this clock" in problem
    assert (
        assess(
            {"feed": Beat("feed", "RUNNING", "", NOW + timedelta(seconds=60))},
            [FEED],
            NOW,
            in_session=True,
        )
        == []
    )
