"""Data-quality checks. Each returns a list of issue strings (empty = pass)."""

from __future__ import annotations

from collections.abc import Iterable

from algo.data.bars import Bar


def validity(bars: Iterable[Bar]) -> list[str]:
    issues = []
    for b in bars:
        tag = f"{b.symbol} {b.ts:%Y-%m-%d %H:%M}"
        if min(b.open, b.high, b.low, b.close) <= 0 or b.volume < 0:
            issues.append(f"{tag}: non-positive price or negative volume")
        if b.high < max(b.open, b.close, b.low):
            issues.append(f"{tag}: high below open/close/low")
        if b.low > min(b.open, b.close, b.high):
            issues.append(f"{tag}: low above open/close/high")
    return issues
