"""One stock's buy/sell decisions over a date range, on a synthetic series. ENGINEERING_TEST_ONLY: nothing here is a strategy
experiment and none of it may enter the validation registry."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D

from algo.data.reader import AdjBar
from algo.strategies.signals import replay
from algo.strategies.trend_pullback import WARMUP, TrendPullbackParams, _indicators

P = TrendPullbackParams()  # trend 200, buy below RSI 25, sell above RSI 60


def days(n, start=date(2025, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars(closes, opens=None):
    ds = days(len(closes))
    return ds, [
        AdjBar(
            datetime.combine(d, time(3, 45), UTC), (opens or closes)[i], c, c, c, D(1000), D(1), 1
        )
        for i, (d, c) in enumerate(zip(ds, closes, strict=True))
    ]


def rising(n, step="0.002"):
    p, out = D(100), []
    for _ in range(n):
        out.append(p)
        p *= 1 + D(step)
    return out


def dipped_then_recovered():
    """A long steady rise, a sharp 6-day drop that stays above the 200-day average, then a strong recovery."""
    out = rising(300)
    p = out[-1]
    for _ in range(6):
        p *= D("0.97")
        out.append(p)
    for _ in range(12):
        p *= D("1.03")
        out.append(p)
    return out


def test_the_numbers_shown_are_the_ones_the_strategy_decides_on():
    closes = [c * (D(1) + D((i * 7) % 11) / 1000) for i, c in enumerate(rising(320))]
    ds, b = bars(closes)
    rows = replay(b, P, ds[0], ds[-1])
    for i in (WARMUP + 200 - 1, 250, 300, 319):
        want = _indicators(b[: i + 1], 200)
        got = next(r for r in rows if r.day == ds[i])
        assert want is not None and (got.close, got.sma, got.rsi) == want and got.ready
    assert not next(
        r for r in rows if r.day == ds[WARMUP + 200 - 2]
    ).ready  # one bar short of enough history


def test_a_dip_inside_an_uptrend_is_bought_and_the_recovery_sold_with_the_next_open_as_the_fill():
    closes = dipped_then_recovered()
    opens = [c + 1 for c in closes]
    ds, b = bars(closes, opens)
    rows = replay(b, P, ds[0], ds[-1])
    acts = [(r.day, r.action, r.reason) for r in rows if r.action]
    assert [a[1] for a in acts] == ["BUY", "SELL"]
    assert acts[0][2] == "oversold in an uptrend" and acts[1][2] == "rsi_above_exit"
    buy = next(r for r in rows if r.action == "BUY")
    nxt = b[ds.index(buy.day) + 1]
    assert (buy.fill_day, buy.fill_price) == (ds[ds.index(buy.day) + 1], nxt.open)
    assert (
        buy.holding_after is True
        and next(r for r in rows if r.action == "SELL").holding_after is False
    )
    assert buy.rsi < P.entry_rsi and buy.close > buy.sma


def test_the_last_day_has_no_next_session_to_fill_on():
    full = dipped_then_recovered()
    ds, b = bars(full)
    buy_day = next(r.day for r in replay(b, P, ds[0], ds[-1]) if r.action == "BUY")
    closes = full[: ds.index(buy_day) + 1]  # the series ends on the day the BUY is decided
    ds, b = bars(closes)
    last = replay(b, P, ds[0], ds[-1])[-1]
    assert last.action == "BUY" and (last.fill_day, last.fill_price) == (None, None)


def test_a_holding_that_loses_the_trend_is_sold_and_one_already_held_is_not_bought_again():
    closes = rising(300)
    p = closes[-1]
    for _ in range(80):
        p *= D("0.99")
        closes.append(p)
    ds, b = bars(closes)
    held = replay(b, P, ds[290], ds[-1], holding=True)
    sells = [r for r in held if r.action == "SELL"]
    assert (
        sells[0].day == ds[290] and sells[0].reason == "rsi_above_exit"
    )  # held in a rally: RSI far above 60, so sold at once
    assert (
        not sells[0].holding_after and sells[-1].reason == "below_trend"
    )  # and the long fall ends with the trend break
    assert all(r.action != "BUY" for r in held[: held.index(sells[0]) + 1])  # held: nothing to buy
    flat = replay(b, P, ds[290], ds[-1], holding=False)
    assert [
        r.action for r in flat if r.action
    ] != []  # not holding at the start: it may buy the dip first


def test_only_the_asked_days_are_returned_but_the_history_before_them_is_used():
    closes = dipped_then_recovered()
    ds, b = bars(closes)
    rows = replay(b, P, ds[310], ds[-1])
    assert rows[0].day == ds[310] and rows[-1].day == ds[-1] and all(r.ready for r in rows)
    assert replay(b, P, ds[-1] + timedelta(days=30), ds[-1] + timedelta(days=60)) == []
    short_ds, short = bars(rising(50))
    assert all(
        not r.ready and r.action is None for r in replay(short, P, short_ds[0], short_ds[-1])
    )


def test_a_shorter_trend_average_is_ready_sooner():
    ds, b = bars(rising(150))
    p100 = TrendPullbackParams(trend_sma=100)
    assert any(r.ready for r in replay(b, p100, ds[0], ds[-1]))
    assert not any(r.ready for r in replay(b, P, ds[0], ds[-1]))
