# ruff: noqa: E501
"""Do two independent price sources agree? Kite's daily candles (adjusted by the vendor for splits and bonuses) against NSE
bhavcopy (raw prices) adjusted by our own corporate-action records. Each instrument's closes are matched by date and the
ratio kite / nse is read:
  MATCH       the sources agree (a stray day or two is tolerated and counted), so the adjustments are corroborated
  STEP        they agree on one side of a date and differ by a steady factor on the other: one source applied (or missed) an
              action. `explained_by` names our action nearest that date (kind, ex-date, status), or None if we hold none
  OFFSET      they differ by a steady factor on every day compared
  DIVERGES    anything else: scattered differences or a step whose size wanders
  NO_OVERLAP  too few common days to judge
NSE's close is a last-30-minute average and Kite's the last trade, so ordinary days differ a little: the default tolerance is
1%, far below the smallest adjustment worth finding (a 1:10 bonus moves prices by 10%).
Nothing here decides which source is right; it finds where they disagree so a person only reviews those names."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from algo.data.reader import IST, Loaded

MIN_DAYS = 20
MAX_OUTLIER_SHARE = Decimal(
    "0.02"
)  # up to 2% of days may be stray before the sources count as disagreeing
STEP_WINDOW = timedelta(days=3)  # an action this close to a step is what explains it
SPREAD_FACTOR = 5  # inside a step the ratio may wander by up to this many tolerances


@dataclass(frozen=True)
class Comparison:
    status: str
    days: int
    outliers: int
    max_deviation: Decimal
    step_date: date | None = None
    step_ratio: Decimal | None = None
    explained_by: tuple[str, date, str] | None = None


def _closes(ld: Loaded) -> dict[date, Decimal]:
    if not ld.rows:
        return {}
    bars = ld.history(ld.days[0], ld.days[-1], adjust="split").bars
    return {b.ts.astimezone(IST).date(): b.close for b in bars}


def _steady(ratios: list[Decimal], tolerance: Decimal) -> bool:
    return max(ratios) - min(ratios) <= tolerance * SPREAD_FACTOR


def compare(kite: Loaded, nse: Loaded, *, tolerance: Decimal = Decimal("0.01")) -> Comparison:
    k, n = _closes(kite), _closes(nse)
    common = sorted(set(k) & set(n))
    if len(common) < MIN_DAYS:
        return Comparison("NO_OVERLAP", len(common), 0, Decimal(0))
    ratio = [k[d] / n[d] for d in common]
    dev = [abs(r - 1) for r in ratio]
    bad = [i for i, d in enumerate(dev) if d > tolerance]
    biggest, size = max(dev), len(common)
    if len(bad) <= MAX_OUTLIER_SHARE * size:
        return Comparison("MATCH", size, len(bad), biggest)
    first, last = bad[0], bad[-1]
    if len(bad) != last - first + 1 or not _steady([ratio[i] for i in bad], tolerance):
        return Comparison("DIVERGES", size, len(bad), biggest)
    typical = sorted(ratio[i] for i in bad)[
        len(bad) // 2
    ]  # an actual observed ratio, not an average of two
    if first == 0 and last == size - 1:
        return Comparison("OFFSET", size, len(bad), biggest, None, typical)
    if first != 0 and last != size - 1:
        return Comparison(
            "DIVERGES", size, len(bad), biggest
        )  # a bump in the middle, not a change that stays
    at = common[last + 1] if first == 0 else common[first]  # where the ratio changes
    near = [r for r in nse.recs if abs(r.ex_date - at) <= STEP_WINDOW]
    nearest = min(near, key=lambda r: abs(r.ex_date - at)) if near else None
    why = None if nearest is None else (nearest.kind, nearest.ex_date, nearest.status)
    return Comparison("STEP", size, len(bad), biggest, at, typical, why)
