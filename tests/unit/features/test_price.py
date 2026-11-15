# ruff: noqa: E501
"""Each feature against numbers worked out by hand, then the rules every feature shares."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

from hypothesis import given, settings
from hypothesis import strategies as st

from algo.features import price
from algo.features._shared import SessionBar, q

DAYS = [
    date(2026, 1, 5) + timedelta(days=i) for i in range(8)
]  # eight consecutive sessions (weekends do not matter to the maths)


def at(day, extra_hours=0):
    return datetime(day.year, day.month, day.day, 13, 0, tzinfo=UTC) + timedelta(hours=extra_hours)


def bar(day, close, high=None, low=None, raw_close=None, raw_vol=1000, extra_hours=0):
    close = D(str(close))
    return SessionBar(day, D(str(high)) if high is not None else close, D(str(low)) if low is not None else close, close,
                      D(str(raw_close)) if raw_close is not None else close, D(raw_vol), at(day, extra_hours))  # fmt: skip


def series(closes, **kw):
    return {d: bar(d, c, **kw) for d, c in zip(DAYS, closes, strict=False)}


# ---- hand-worked values -----------------------------------------------------------------------------------------
def test_ret_is_close_over_the_close_n_sessions_back_and_absent_during_warm_up():
    bars = series([100, 102, 101, 105, 107, 106, 110, 108])
    r = price.ret(5)(DAYS, bars)
    assert sorted(r) == DAYS[5:]  # six closes are needed: days 1-5 have no value, not zero
    assert r[DAYS[5]][0] == D("0.06")  # 106 / 100 - 1
    assert r[DAYS[6]][0] == D("0.078431372549")  # 110 / 102 - 1
    assert r[DAYS[7]][0] == D("0.069306930693")  # 108 / 101 - 1


def test_vol_is_the_sample_standard_deviation_of_the_daily_returns():
    bars = series([100, 110, 99, "108.9"])  # daily returns +10%, -10%, +10% exactly
    v = price.vol(3)(DAYS[:4], bars)
    assert sorted(v) == [DAYS[3]]
    assert v[DAYS[3]][0] == D("0.115470053838")  # sample stdev of (0.1, -0.1, 0.1) = 0.2 / sqrt(3)


def test_atr_is_wilders_first_the_mean_of_n_true_ranges_then_the_recursion():
    bars = {
        DAYS[0]: bar(DAYS[0], 100, 102, 98), DAYS[1]: bar(DAYS[1], 110, 112, 108),
        DAYS[2]: bar(DAYS[2], 99, 111, 97), DAYS[3]: bar(DAYS[3], "108.9", 110, 100),
        DAYS[4]: bar(DAYS[4], 106, 112, 104),
    }  # fmt: skip
    # true ranges: day1 max(4, 12, 8) = 12; day2 max(14, 1, 13) = 14; day3 max(10, 11, 1) = 11; day4 max(8, 3.1, 4.9) = 8
    a = price.atr(3)(DAYS[:5], bars)
    assert sorted(a) == [DAYS[3], DAYS[4]]
    assert a[DAYS[3]][0] == D("12.333333333333")  # (12 + 14 + 11) / 3
    assert a[DAYS[4]][0] == D("10.888888888889")  # (12.3333.. * 2 + 8) / 3
    p = price.atr_pct(3)(DAYS[:5], bars)
    assert p[DAYS[3]][0] == q(D(37) / D(3) / D("108.9"))  # the unrounded ATR over the close
    assert p[DAYS[4]][0] == q((D(37) / D(3) * 2 + 8) / 3 / 106)


def test_dist_sma_is_the_close_over_the_mean_of_the_last_n_closes_minus_one():
    bars = series([100, 110, 99, "108.9"])
    d = price.dist_sma(3)(DAYS[:4], bars)
    assert sorted(d) == DAYS[2:4]  # n = 3 closes are needed
    assert d[DAYS[3]][0] == D(
        "0.027681660900"
    )  # 108.9 / ((110 + 99 + 108.9) / 3) - 1 = 326.7 / 317.9 - 1


def test_traded_value_uses_the_raw_close_and_raw_volume_not_the_adjusted_close():
    bars = {
        DAYS[0]: bar(DAYS[0], 50, raw_close=100, raw_vol=10),   # adjusted close 50, but the rupees traded were 100 x 10
        DAYS[1]: bar(DAYS[1], 51, raw_close=102, raw_vol=20),
        DAYS[2]: bar(DAYS[2], 52, raw_close=104, raw_vol=30),
    }  # fmt: skip
    t = price.traded_value(3)(DAYS[:3], bars)
    assert sorted(t) == [DAYS[2]] and t[DAYS[2]][0] == D(
        "2053.333333333333"
    )  # (1000 + 2040 + 3120) / 3, not the adjusted prices


# ---- rules every feature shares ----------------------------------------------------------------------------------
def test_a_window_with_a_missing_session_has_no_value_and_nothing_is_filled_in():
    bars = series([100, 102, 101, 105, 107, 106, 110, 108])
    del bars[DAYS[2]]  # a halted session: no bar
    r = price.ret(3)(DAYS, bars)
    assert (
        DAYS[3] not in r and DAYS[4] not in r and DAYS[5] not in r
    )  # every window that contains day 2
    assert r[DAYS[6]][0] == q(
        D(110) / D(105) - 1
    )  # the first window clear of the gap is computed normally
    # an ATR chain breaks at the gap and must warm up again from scratch
    full = {d: bar(d, 100 + i, 101 + i, 99 + i) for i, d in enumerate(DAYS)}
    del full[DAYS[4]]
    a = price.atr(2)(DAYS, full)
    assert sorted(a) == [
        DAYS[2],
        DAYS[3],
        DAYS[7],
    ]  # three bars start a chain (day 2); day 4 breaks it; days 5, 6, 7 start the next one


def test_available_at_is_the_latest_of_every_input_not_the_value_days_own():
    bars = series([100, 102, 101, 105])
    late = bars[DAYS[1]]
    bars[DAYS[1]] = SessionBar(
        late.day,
        late.high,
        late.low,
        late.close,
        late.raw_close,
        late.raw_volume,
        at(DAYS[1], extra_hours=100),
    )  # arrived very late
    r = price.ret(3)(DAYS[:4], bars)
    assert r[DAYS[3]][1] == at(
        DAYS[1], extra_hours=100
    )  # the window's slowest input, later than the value day's own bar
    assert price.dist_sma(2)(DAYS[:4], bars)[DAYS[3]][1] == at(
        DAYS[3]
    )  # a window that does not reach the late bar is not delayed by it


closes = st.lists(
    st.decimals(min_value=D("1"), max_value=D("5000"), places=2), min_size=2, max_size=14
)


@settings(max_examples=60, deadline=None)
@given(closes)
def test_a_batch_over_a_series_equals_computing_one_day_at_a_time(cs):
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(len(cs))]
    bars = {
        d: bar(d, c, c + 1, c - D("0.5") if c > 1 else c, c, 100 + i)
        for i, (d, c) in enumerate(zip(days, cs, strict=True))
    }
    for f in (
        price.ret(3),
        price.vol(3),
        price.atr(3),
        price.atr_pct(3),
        price.dist_sma(4),
        price.traded_value(4),
    ):
        batch = f(days, bars)
        for k, d in enumerate(days):
            incremental = f(days[: k + 1], {x: bars[x] for x in days[: k + 1]})
            assert incremental.get(d) == batch.get(
                d
            )  # a value never depends on what comes after it
