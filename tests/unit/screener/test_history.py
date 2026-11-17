# ruff: noqa: E501
"""The point-in-time price fields behind the score history: a day's figures use only bars up to that day, and a window never reaches back across a split."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from algo.screener.history import technical_frame

START = date(2024, 1, 1)


def bars(iid, n=320, seed=1, split_at=None):
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    if split_at is not None:
        close[split_at:] = close[split_at:] / 2  # a 2-for-1 split: the unadjusted close halves
    days = [START + timedelta(days=i) for i in range(n)]
    return pd.DataFrame(
        {"instrument_id": iid, "d": days, "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
         "volume": rng.integers(1_000, 5_000, n).astype(float), "delivery_qty": rng.integers(300, 900, n).astype(float)}
    )  # fmt: skip


NO_SPLITS = pd.DataFrame({"instrument_id": [], "ex_date": []})


def test_a_days_figures_do_not_change_when_later_bars_are_removed():
    full = pd.concat([bars(1), bars(2, seed=2)])
    day = START + timedelta(days=299)
    cut = full[full["d"] <= day]
    a = technical_frame(full, NO_SPLITS, [day]).set_index("instrument_id").drop(columns="d")
    b = technical_frame(cut, NO_SPLITS, [day]).set_index("instrument_id").drop(columns="d")
    pd.testing.assert_frame_equal(a, b)
    assert a.notna().all().all()  # a 300-day history has every price field


def test_a_window_does_not_cross_a_split_so_a_halved_price_is_not_read_as_a_crash():
    day = START + timedelta(days=210)
    splits = pd.DataFrame({"instrument_id": [1], "ex_date": [START + timedelta(days=200)]})
    got = technical_frame(
        pd.concat([bars(1, split_at=200), bars(2, seed=2)]), splits, [day]
    ).set_index("instrument_id")
    assert pd.isna(got.loc[1, "chg_1m"]) and pd.isna(
        got.loc[1, "price_vs_sma50"]
    )  # only 10 bars since the split: unknown, not -50%
    assert pd.notna(got.loc[2, "chg_1m"])
    raw = technical_frame(pd.concat([bars(1, split_at=200)]), NO_SPLITS, [day]).set_index(
        "instrument_id"
    )
    assert (
        raw.loc[1, "chg_1m"] < -30
    )  # without the cut the split shows up as a crash: the cut is what prevents it


def test_only_the_asked_for_days_with_a_bar_are_returned_and_missing_delivery_stays_missing():
    b = bars(1)
    b.loc[b["d"] == START + timedelta(days=300), "delivery_qty"] = np.nan
    days = [START + timedelta(days=300), START + timedelta(days=400)]  # the second day has no bar
    got = technical_frame(b, NO_SPLITS, days)
    assert list(got["d"]) == [days[0]] and pd.isna(got.loc[0, "delivery_pct"])


@pytest.mark.parametrize(
    ("col", "scaled"), [("volume_ratio", "volume"), ("delivery_vs_avg", "delivery_qty")]
)
def test_ratios_use_only_earlier_days_as_their_norm(col, scaled):
    b = bars(1)
    day = START + timedelta(days=300)
    base = technical_frame(b, NO_SPLITS, [day])[col].iloc[0]
    b.loc[b["d"] == day, scaled] *= 10  # a spike today, against a norm made of the days before
    assert technical_frame(b, NO_SPLITS, [day])[col].iloc[0] > base * 5
