from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from algo.data.bars import SPECS, Bar, Freq


def test_registry_covers_every_freq_and_specs_are_read_only():
    assert set(SPECS) == set(Freq)
    assert SPECS[Freq.D1].table == "bar_1d" and SPECS[Freq.M1].table == "bar_1m"
    with pytest.raises(TypeError):
        SPECS[Freq.D1] = None  # type: ignore[index]


def test_bar_defaults_and_immutable():
    b = Bar("X", datetime(2026, 1, 5, 3, 45, tzinfo=UTC), D(1), D(2), D(1), D(2), D(10))
    assert dict(b.extra) == {}
    with pytest.raises(FrozenInstanceError):
        b.symbol = "Y"  # type: ignore[misc]
