"""Exact decimal helpers. Prices/quantities are Decimal, never float."""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal


def _step(step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("step must be positive")
    return step


def snap_down(value: Decimal, step: Decimal) -> Decimal:
    """Largest multiple of step <= value (use for quantities: never oversize)."""
    return (value / _step(step)).to_integral_value(ROUND_DOWN) * step


def snap_nearest(value: Decimal, step: Decimal) -> Decimal:
    """Nearest multiple of step, ties to even (use for prices to tick size)."""
    return (value / _step(step)).to_integral_value(ROUND_HALF_EVEN) * step
