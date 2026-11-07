from datetime import date
from pathlib import Path

import pytest

from algo.core.calendar import nse
from algo.data.providers.base import ParseError
from algo.data.providers.nse_holidays import parse_holidays

RAW = (Path(__file__).parents[2] / "data/nse/holiday_master_sample.json").read_bytes()  # real


def test_real_cm_holidays_weekday_only_with_muhurat_flagged():
    h = parse_holidays(RAW)
    assert date(2026, 1, 26) in h.weekday_holidays and date(2026, 11, 10) in h.weekday_holidays
    assert date(2026, 2, 15) not in h.weekday_holidays  # Sunday
    assert h.special_review == [(date(2026, 11, 8), "Diwali Laxmi Pujan*")]
    assert len(h.weekday_holidays) == 16  # 20 CM entries minus 4 on weekends


def test_feeds_calendar():
    cal = nse(parse_holidays(RAW).weekday_holidays)
    assert not cal.is_trading_day(date(2026, 11, 10)) and cal.is_trading_day(date(2026, 11, 11))
    assert not cal.is_trading_day(date(2026, 1, 15))  # municipal-election holiday


@pytest.mark.parametrize(
    "raw", [b"x", b'{"FO":[]}', b'{"CM":[{"tradingDate":"bad","description":"x"}]}']
)
def test_bad_input(raw):
    with pytest.raises(ParseError):
        parse_holidays(raw)
