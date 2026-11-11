"""NSE holiday-master JSON -> trading holidays for one segment (CM = equities).
The feed lists only the current calendar year. Weekend entries marked with '*' (e.g. Diwali
Laxmi Pujan*) are Muhurat sessions whose times are announced later: returned for manual entry."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from algo.data.providers.base import ParseError


@dataclass(frozen=True)
class Holidays:
    weekday_holidays: frozenset[date]
    special_review: list[tuple[date, str]]  # needs manually entered session times
    names: dict[date, str] = field(
        default_factory=dict
    )  # NSE's description of every listed day, weekends included


def parse_holidays(raw: bytes, segment: str = "CM") -> Holidays:
    try:
        rows = json.loads(raw)[segment]
        hol, special, names = set(), [], {}
        for r in rows:
            d = datetime.strptime(r["tradingDate"], "%d-%b-%Y").replace(tzinfo=UTC).date()
            desc = r["description"]
            names[d] = desc
            if desc.endswith("*"):
                special.append((d, desc))
            if d.weekday() < 5:
                hol.add(d)
        return Holidays(frozenset(hol), special, names)
    except (KeyError, ValueError, TypeError) as e:
        raise ParseError(str(e)) from e
