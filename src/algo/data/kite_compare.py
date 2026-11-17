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
1%, far below the smallest adjustment worth finding (a 1:10 bonus moves prices by 10%). Kite also rounds to its 0.05 tick, which is
a large share of a heavily adjusted old price of about half a rupee (0.025 of 0.50 is 5%): each day therefore also allows half a tick.
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
HALF_TICK = Decimal(
    "0.025"
)  # Kite quotes in 0.05 steps: a price may be off by half a step from rounding alone


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


def _steady(ratios: list[Decimal], tolerance: Decimal, slack: Decimal = Decimal(0)) -> bool:
    return max(ratios) - min(ratios) <= tolerance * SPREAD_FACTOR + slack


def compare(kite: Loaded, nse: Loaded, *, tolerance: Decimal = Decimal("0.01")) -> Comparison:
    k, n = _closes(kite), _closes(nse)
    common = sorted(set(k) & set(n))
    if len(common) < MIN_DAYS:
        return Comparison("NO_OVERLAP", len(common), 0, Decimal(0))
    ratio = [k[d] / n[d] for d in common]
    dev = [abs(r - 1) for r in ratio]
    rounding = [
        HALF_TICK / n[d] for d in common
    ]  # what Kite's tick alone can move the ratio on that day
    bad = [i for i, d in enumerate(dev) if d > tolerance + rounding[i]]
    biggest, size = max(dev), len(common)
    if len(bad) <= MAX_OUTLIER_SHARE * size:
        return Comparison("MATCH", size, len(bad), biggest)
    first, last = bad[0], bad[-1]
    if len(bad) != last - first + 1 or not _steady(
        [ratio[i] for i in bad], tolerance, 2 * max(rounding[i] for i in bad)
    ):
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


def breaches(results: dict[str, Comparison]) -> dict[str, str]:
    """symbol -> why, for the comparisons a person must look at: the sources diverge, differ by a steady offset, or step with no recorded action near the step.
    A match, too little overlap, and a step our own records explain are not breaches."""
    out: dict[str, str] = {}
    for sym, r in results.items():
        if r.status == "DIVERGES":
            out[sym] = f"DIVERGES: scattered differences, largest {r.max_deviation:.3f}"
        elif r.status == "OFFSET":
            out[sym] = f"OFFSET: a steady difference on every day, largest {r.max_deviation:.3f}"
        elif r.status == "STEP" and r.explained_by is None:
            out[sym] = (
                f"STEP: no recorded action near {r.step_date} (x{r.step_ratio:.4f})"
                if r.step_ratio
                else f"STEP: no recorded action near {r.step_date}"
            )
    return out
