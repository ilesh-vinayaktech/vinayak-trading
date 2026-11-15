from datetime import UTC, datetime, timedelta

import pytest

from algo.data.store.migrate import migrate
from algo.live.consumer import BarConsumer, data_fresh

pytestmark = pytest.mark.integration
T0 = datetime(2026, 11, 16, 4, 0, tzinfo=UTC)  # 09:30 IST


@pytest.fixture
def env(conn):
    migrate(conn)
    conn.execute(
        "SET session_replication_role = replica"
    )  # the instruments behind the bars are not what is tested here
    return conn


def put(conn, iid, minute, built, close="100", partial=False):
    """A bar of instrument `iid` for the minute `T0 + minute`, written (built) at `T0 + built` seconds. A duplicate changes nothing."""
    conn.execute(
        "INSERT INTO live_bar_1m (instrument_id, ts, open, high, low, close, volume, ticks, partial, built_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,10,3,%s,%s) ON CONFLICT DO NOTHING",
        (
            iid,
            T0 + timedelta(minutes=minute),
            close,
            close,
            close,
            close,
            partial,
            T0 + timedelta(seconds=built),
        ),
    )


def seen(rows):
    return [(r.instrument_id, int((r.ts - T0).total_seconds() // 60)) for r in rows]


def consumer(conn, name="runner"):
    return BarConsumer(conn, name, start_after=T0 - timedelta(hours=1))


def test_a_consumer_gets_each_bar_once_in_the_order_it_was_written_and_commit_moves_it_on(env):
    put(env, 2, 0, 10)
    put(env, 1, 0, 10)
    put(env, 1, 1, 70)
    c = consumer(env)
    first = c.poll()
    assert seen(first) == [(1, 0), (2, 0), (1, 1)]  # by write time, then instrument, then minute
    assert seen(c.poll()) == [(1, 0), (2, 0), (1, 1)]  # nothing is consumed until committed
    c.commit(first, T0)
    assert c.poll() == []
    put(env, 1, 2, 130)
    assert seen(c.poll()) == [(1, 2)]


def test_a_restart_neither_reprocesses_nor_skips_a_bar(env):
    put(env, 1, 0, 10)
    put(env, 2, 0, 10)
    a = consumer(env)
    a.commit(a.poll(limit=1), T0)  # only the first of two was handled before the process died
    put(env, 1, 1, 70)
    b = consumer(env)  # the restarted process: same name, nothing in memory
    assert seen(b.poll()) == [
        (2, 0),
        (1, 1),
    ]  # the second bar is still there, the first is not repeated
    b.commit(b.poll(), T0)
    assert consumer(env).poll() == []


def test_a_handler_that_fails_leaves_the_offset_where_it_was_so_the_bars_come_again(env):
    put(env, 1, 0, 10)
    c = consumer(env)
    handled = []

    def boom(rows):
        handled.append(seen(rows))
        raise RuntimeError("the strategy runner crashed")

    with pytest.raises(RuntimeError):
        c.run_once(boom, T0)
    assert (
        c.run_once(lambda rows: handled.append(seen(rows)), T0) == 1
    )  # redelivered: at-least-once
    assert handled == [[(1, 0)], [(1, 0)]]
    assert c.run_once(lambda rows: handled.append("never"), T0) == 0  # and now it is done
    assert len(handled) == 2


def test_the_handlers_own_writes_and_the_offset_commit_or_roll_back_together(env):
    env.execute("CREATE TABLE seen_bars (instrument_id BIGINT, minute INT)")
    put(env, 1, 0, 10)
    c = consumer(env)

    def write_then_fail(rows):
        env.execute("INSERT INTO seen_bars VALUES (1, 0)")
        raise RuntimeError("died after writing")

    with pytest.raises(RuntimeError):
        c.run_once(write_then_fail, T0)
    assert (
        env.execute("SELECT count(*) FROM seen_bars").fetchone()[0] == 0
    )  # the write was undone with the offset
    c.run_once(lambda rows: env.execute("INSERT INTO seen_bars VALUES (1, 0)"), T0)
    assert env.execute("SELECT count(*) FROM seen_bars").fetchone()[0] == 1


def test_a_bar_the_feed_sends_twice_is_delivered_once(env):
    put(env, 1, 0, 10, close="100")
    c = consumer(env)
    c.commit(c.poll(), T0)
    put(
        env, 1, 0, 90, close="999"
    )  # the feed repeats it: the first copy stands, nothing new is written
    assert c.poll() == []


def test_a_bar_that_arrives_late_for_an_earlier_minute_is_still_delivered(env):
    put(env, 1, 5, 400)
    c = consumer(env)
    c.commit(c.poll(), T0)
    put(env, 2, 3, 500)  # minute 3 written after minute 5 was already handled
    assert seen(c.poll()) == [(2, 3)]


def test_consumers_keep_separate_offsets_and_a_new_one_starts_after_the_given_moment_not_at_the_beginning(
    env,
):
    put(env, 1, 0, 10)
    put(env, 1, 1, 70)
    a, b = consumer(env, "a"), consumer(env, "b")
    a.commit(a.poll(), T0)
    assert b.poll() != [] and a.poll() == []
    late = BarConsumer(env, "late", start_after=T0 + timedelta(seconds=30))
    assert seen(late.poll()) == [(1, 1)]  # only what was written after its start


def test_the_data_is_fresh_only_while_the_feed_is_connected_and_its_last_bar_is_recent(env):
    assert data_fresh(env, T0, timedelta(minutes=3)) == "there is no feed status"

    def feed(state, last_bar):
        env.execute("DELETE FROM feed_status")
        env.execute(
            "INSERT INTO feed_status (feed_id, state, detail, subscribed, last_bar_at, ticks_total, bars_total, bad_frames, late_ticks, updated_at)"
            " VALUES (1, %s, '', 10, %s, 0, 0, 0, 0, %s)",
            (state, last_bar, T0),
        )

    feed("CONNECTED", T0 - timedelta(minutes=2))
    assert data_fresh(env, T0, timedelta(minutes=3)) is None
    feed("CONNECTED", T0 - timedelta(minutes=4))
    assert "4 minutes" in data_fresh(env, T0, timedelta(minutes=3))
    feed("CONNECTED", None)
    assert "no bar" in data_fresh(env, T0, timedelta(minutes=3))
    feed("RECONNECTING", T0)
    assert "RECONNECTING" in data_fresh(env, T0, timedelta(minutes=3))
