"""Moving-average and window primitives for indicators, over Decimal series.

A series is a list the length of the bars; None marks a bar with no value yet (warm-up). All inputs
are Decimal (prices are never floats). The smoothing conventions follow TradingView's Pine
definitions so that values agree with what a trader sees there:
  SMA        plain mean of the last n values
  EMA        alpha = 2/(n+1), seeded with the SMA of the first n values
  RMA        Wilder's smoothing, alpha = 1/n, seeded with the SMA of the first n values
  stdev      POPULATION standard deviation (Pine's ta.stdev), not the sample one
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

Series = list[Decimal | None]
ZERO = Decimal(0)
ONE = Decimal(1)


def _first_valid(x: Sequence[Decimal | None]) -> int | None:
    return next((i for i, v in enumerate(x) if v is not None), None)


def _values(x: Sequence[Decimal | None], lo: int, hi: int) -> list[Decimal]:
    return [v for v in x[lo : hi + 1] if v is not None]


def sma(x: Sequence[Decimal | None], n: int) -> Series:
    out: Series = [None] * len(x)
    f = _first_valid(x)
    if f is None or n < 1:
        return out
    for i in range(f + n - 1, len(x)):
        window = x[i - n + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum((v for v in window if v is not None), ZERO) / n
    return out


def _recursive(x: Sequence[Decimal | None], n: int, alpha: Decimal) -> Series:
    out: Series = [None] * len(x)
    seed = sma(x, n)
    prev: Decimal | None = None
    for i, v in enumerate(x):
        if prev is None:
            prev = seed[i]
            out[i] = prev
        elif v is not None:
            prev = alpha * v + (ONE - alpha) * prev
            out[i] = prev
    return out


def ema(x: Sequence[Decimal | None], n: int) -> Series:
    return _recursive(x, n, Decimal(2) / (n + 1))


def rma(x: Sequence[Decimal | None], n: int) -> Series:
    return _recursive(x, n, ONE / n)


def wma(x: Sequence[Decimal | None], n: int) -> Series:
    out: Series = [None] * len(x)
    f = _first_valid(x)
    if f is None or n < 1:
        return out
    denom = Decimal(n * (n + 1) // 2)
    for i in range(f + n - 1, len(x)):
        window = x[i - n + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum((v * (k + 1) for k, v in enumerate(window) if v is not None), ZERO) / denom
    return out


def stdev(x: Sequence[Decimal | None], n: int) -> Series:
    out: Series = [None] * len(x)
    mean = sma(x, n)
    for i, m in enumerate(mean):
        if m is None:
            continue
        window = _values(x, i - n + 1, i)
        out[i] = (sum(((v - m) ** 2 for v in window), ZERO) / n).sqrt()
    return out


def highest(x: Sequence[Decimal], n: int) -> Series:
    return [max(x[i - n + 1 : i + 1]) if i >= n - 1 else None for i in range(len(x))]


def lowest(x: Sequence[Decimal], n: int) -> Series:
    return [min(x[i - n + 1 : i + 1]) if i >= n - 1 else None for i in range(len(x))]


def true_range(high: Sequence[Decimal], low: Sequence[Decimal], close: Sequence[Decimal]) -> Series:
    out: Series = []
    for i in range(len(high)):
        if i == 0:
            out.append(high[0] - low[0])
        else:
            pc = close[i - 1]
            out.append(max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc)))
    return out


def change(x: Sequence[Decimal]) -> Series:
    return [None] + [x[i] - x[i - 1] for i in range(1, len(x))]
