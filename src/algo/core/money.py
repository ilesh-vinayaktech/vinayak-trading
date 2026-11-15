"""Exact decimal helpers. Prices/quantities are Decimal, never float."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_EVEN, Decimal


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


def snap_up(value: Decimal, step: Decimal) -> Decimal:
    """Smallest multiple of step >= value."""
    return (value / _step(step)).to_integral_value(ROUND_CEILING) * step


def snap_limit(side: str, limit: Decimal, tick: Decimal) -> Decimal:
    """A tick-grid limit that never crosses the stated one: a BUY snaps down, a SELL up."""
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    return snap_down(limit, tick) if side == "BUY" else snap_up(limit, tick)
