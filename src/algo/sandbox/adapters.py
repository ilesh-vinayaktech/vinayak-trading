# ruff: noqa: E501
"""Carrying a strategy's constructor arguments and audit rows across the process boundary. Strategies are built from objects
(here an IntervalMembership) that JSON cannot hold: the host sends a plain description and names the function that rebuilds the object
inside the worker (only functions in this module can be named), and the audit row comes back with its integer keys restored."""

from __future__ import annotations

from datetime import date
from typing import Any

from algo.data.universe import Interval
from algo.strategies.nifty200_momentum import IntervalMembership


def membership_spec(m: IntervalMembership) -> dict[str, Any]:
    return {
        "intervals": [[i.instrument_id, i.start, i.end] for i in m._ivs],
        "unusable": [[d, why] for d, why in m._unusable.items()],
    }


def membership(spec: dict[str, Any]) -> IntervalMembership:
    return IntervalMembership(
        [Interval(i, start, end) for i, start, end in spec["intervals"]],
        {d: why for d, why in spec["unusable"] if isinstance(d, date)},
    )


def restore_audit(row: dict[str, Any]) -> dict[str, Any]:
    """JSON turns the integer keys of `exits` into strings; the runner looks them up by instrument id."""
    if isinstance(row.get("exits"), dict):
        return {**row, "exits": {int(k): v for k, v in row["exits"].items()}}
    return row
