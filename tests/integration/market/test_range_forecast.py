# ruff: noqa: E501
"""The live expected-range forecast: made once before the open, never replaced, only when the data is current, and resolved with the session's actual range."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from algo.data.store.migrate import migrate
from algo.market import range_forecast as rf
from algo.market import volatility as vol

pytestmark = pytest.mark.integration
IST = ZoneInfo("Asia/Kolkata")
N = 760  # sessions with candles: enough for 500 training rows and a forecast
START = date(2021, 1, 4)


def weekdays(n, start=START):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = weekdays(N + 1)  # the last day is the session being forecast
TODAY = DAYS[-1]
NOW = datetime(TODAY.year, TODAY.month, TODAY.day, 8, 55, tzinfo=IST).astimezone(UTC)


def put_bars(conn, upto):
    rng = np.random.default_rng(4)
    px = 20000.0
    for d in DAYS[:upto]:
        o = px * (1 + rng.normal(0, 0.002))
        c = o * (1 + rng.normal(0, 0.007))
        hi, lo = (
            max(o, c) * (1 + abs(rng.normal(0, 0.004))),
            min(o, c) * (1 - abs(rng.normal(0, 0.004))),
        )
        px = c
        conn.execute(
            "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE','NIFTY 500',%s,%s,%s,%s,%s,1,%s)",
            (d, o, hi, lo, c, NOW),
        )
        conn.execute(
            "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE','INDIA VIX',%s,15,16,14,%s,2,%s)",
            (d, 15 + 5 * abs(rng.normal()), NOW),
        )


def put_us(conn, upto):
    rng = np.random.default_rng(8)
    for sym in ("SP500", "VIXUS"):
        px = 100.0
        for d in DAYS[:upto]:
            px *= 1 + rng.normal(0, 0.01)
            conn.execute(
                "INSERT INTO global_daily (symbol, day, close, source, ingested_at) VALUES (%s,%s,%s,'test',%s)",
                (sym, d, px, NOW),
            )


@pytest.fixture
def ready(conn):
    migrate(conn)
    put_bars(conn, N)  # candles up to the day before TODAY
    put_us(conn, N)  # US closes up to the session before TODAY's open
    return conn


def test_a_forecast_is_made_once_with_its_evidence_and_never_replaced(ready):
    out = rf.make(ready, NOW)
    assert out.status == "made" and out.forecast_range is not None and 0.2 < out.forecast_range < 5
    row = ready.execute(
        "SELECT as_of, model_version, made_at, forecast_range, features, train_through, n_train FROM range_forecast_log"
    ).fetchone()
    assert row[0] == DAYS[-2] and row[1] == "range-ridge-v1" and row[2] == NOW
    assert set(row[4]) == set(vol.FEATURES) and row[5] < row[0] and row[6] >= vol.MIN_TRAIN
    ready.execute(
        "UPDATE index_bar_1d SET high = high * 1.5 WHERE exchange='NSE'"
    )  # the data changes: a made forecast must not
    again = rf.make(ready, NOW)
    assert again.status == "exists"
    assert ready.execute("SELECT forecast_range FROM range_forecast_log").fetchone()[
        0
    ] == pytest.approx(row[3])


def test_no_forecast_on_a_closed_day_or_when_the_last_candle_is_not_the_previous_session(ready):
    saturday = datetime(2026, 11, 14, 8, 55, tzinfo=IST).astimezone(UTC)
    assert rf.make(ready, saturday).status == "closed"
    ready.execute(
        "DELETE FROM index_bar_1d WHERE trade_date=%s", (DAYS[-2],)
    )  # last night's candle is missing
    out = rf.make(ready, NOW)
    assert out.status == "stale" and "load the index candles" in out.detail
    assert ready.execute("SELECT count(*) FROM range_forecast_log").fetchone()[0] == 0


def test_no_forecast_while_the_us_closes_or_india_vix_are_not_in(ready):
    ready.execute(
        "DELETE FROM global_daily WHERE symbol='SP500' AND day=%s", (DAYS[-2],)
    )  # the US session before today is missing
    out = rf.make(ready, NOW)
    assert (
        out.status == "no_inputs"
        and ready.execute("SELECT count(*) FROM range_forecast_log").fetchone()[0] == 0
    )


def test_a_forecast_is_resolved_with_the_actual_range_and_stays_as_it_was(ready):
    rf.make(ready, NOW)
    before = ready.execute("SELECT forecast_range, features FROM range_forecast_log").fetchone()
    assert rf.resolve(ready) == 0  # today has not traded
    ready.execute(
        "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE','NIFTY 500',%s,20000,20150,19900,20050,1,%s)",
        (TODAY, NOW),
    )
    assert rf.resolve(ready) == 1 and rf.resolve(ready) == 0
    got = ready.execute(
        "SELECT forecast_range, features, actual_range, target_day FROM range_forecast_log"
    ).fetchone()
    assert got[2] == pytest.approx(100 * (20150 - 19900) / 20000) and got[3] == TODAY
    assert (got[0], got[1]) == before  # resolving never touches the forecast
