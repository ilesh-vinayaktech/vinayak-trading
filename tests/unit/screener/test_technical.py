from decimal import Decimal as D

from algo.indicators.catalog import Bars
from algo.screener.technical import technicals


def bars(close, vol=1000):
    c = [D(str(x)) for x in close]
    return Bars(c, c, c, c, [D(vol)] * len(c))


def test_a_steady_rise_has_known_changes_and_averages():
    t = technicals(bars(range(1, 301)))
    assert t["price"] == 300 and t["chg_1d"] == (D(300) / 299 - 1) * 100
    assert t["chg_1y"] == (D(300) / 48 - 1) * 100
    assert t["sma50_vs_sma200"] > 0 and t["price_vs_sma200"] > 0
    assert t["pct_from_52w_high"] == 0 and t["pct_from_52w_low"] > 0
    assert t["rsi_14"] == 100 and t["volume_ratio"] == 1
    assert t["turnover_cr"] == D(300) * 1000 / 10_000_000 or t["turnover_cr"] > 0


def test_short_history_gives_none_not_zero():
    t = technicals(bars([10, 11, 12]))
    assert t["chg_1d"] is not None and t["chg_1w"] is None
    assert all(
        t[k] is None
        for k in (
            "rsi_14",
            "macd_hist",
            "adx_14",
            "price_vs_sma200",
            "pct_from_52w_high",
            "turnover_cr",
        )
    )


def test_no_bars_at_all():
    assert technicals(bars([]))["price"] is None


def test_asking_for_some_fields_gives_the_same_values_for_those_and_skips_the_slow_indicators():
    b = bars(range(1, 301))
    full = technicals(b)
    some = technicals(b, fields={"chg_1m", "price_vs_sma50", "rsi_14"})
    for k in ("price", "chg_1m", "price_vs_sma50", "rsi_14"):
        assert some[k] == full[k]
    assert some["macd_hist"] is None and some["adx_14"] is None  # not asked for, so not worked out
    assert set(some) == set(full)  # the same keys either way
