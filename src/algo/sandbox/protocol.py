# ruff: noqa: E501
"""The wire format between the platform and a strategy worker: one JSON object per line. Decimals, datetimes, dates and
bars travel as tagged values so nothing is rounded or reinterpreted in transit, and the same input always encodes to
the same bytes (sorted keys), which is what makes a replayed run comparable."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

BAR_FIELDS = ("ts", "open", "high", "low", "close", "volume", "factor", "owner")


class ProtocolError(ValueError):
    pass


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return {"$d": str(o)}
    if isinstance(o, datetime):  # before date: a datetime is a date
        return {"$t": o.isoformat()}
    if isinstance(o, date):
        return {"$date": o.isoformat()}
    if (
        is_dataclass(o)
        and not isinstance(o, type)
        and tuple(f.name for f in fields(o)) == BAR_FIELDS
    ):
        return {
            "$bar": [
                _default(getattr(o, n))
                if not isinstance(getattr(o, n), (int, type(None)))
                else getattr(o, n)
                for n in BAR_FIELDS
            ]
        }
    raise ProtocolError(f"cannot send a {type(o).__name__}")


def _hook(d: dict[str, Any]) -> Any:
    if len(d) == 1:
        ((k, v),) = d.items()
        if k == "$d":
            return Decimal(v)
        if k == "$t":
            return datetime.fromisoformat(v)
        if k == "$date":
            return date.fromisoformat(v)
        if k == "$bar":
            return Bar(*v)
    return d


class Bar:
    """What a strategy sees of a bar in the worker: the same attributes as the platform's AdjBar, nothing else."""

    __slots__ = BAR_FIELDS

    def __init__(
        self,
        ts: datetime,
        open: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal,
        factor: Decimal,
        owner: int | None,
    ) -> None:
        self.ts, self.open, self.high, self.low, self.close = ts, open, high, low, close
        self.volume, self.factor, self.owner = volume, factor, owner

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Bar) and all(
            getattr(self, n) == getattr(other, n) for n in BAR_FIELDS
        )

    def __hash__(self) -> int:
        return hash(tuple(getattr(self, n) for n in BAR_FIELDS))

    def __repr__(self) -> str:
        return f"Bar({self.ts:%Y-%m-%d} close={self.close})"


def dumps(msg: dict[str, Any]) -> str:
    try:
        return json.dumps(
            msg, default=_default, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as e:
        raise ProtocolError(str(e)) from e


def loads(line: str) -> dict[str, Any]:
    try:
        msg = json.loads(line, object_hook=_hook)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"not JSON: {e}") from e
    if not isinstance(msg, dict):
        raise ProtocolError("a message is a JSON object")
    return msg
