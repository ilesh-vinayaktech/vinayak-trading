"""Price-continuity data-quality check (spec section 6/7), run on RAW closes + recorded actions:
  unexplained_jump              |close-to-close| > threshold with no split/bonus on that bar
  action_without_discontinuity  a split/bonus whose factor does not match the actual price move
Together these catch missing/unparsed corporate actions AND wrong ratios."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from algo.data.adjust.factors import Adjustment


@dataclass(frozen=True)
class Issue:
    kind: str
    day: date
    detail: str


def continuity_issues(
    closes: Sequence[tuple[date, Decimal]],
    adjustments: Iterable[Adjustment],
    *,
    jump: Decimal = Decimal("0.20"),
    tol: Decimal = Decimal("0.25"),
) -> list[Issue]:
    splits = [a for a in adjustments if a.kind in ("split", "price")]
    issues: list[Issue] = []
    for (d0, c0), (d1, c1) in zip(closes, closes[1:], strict=False):
        ratio = c1 / c0
        expected = Decimal(1)
        for a in splits:
            if d0 < a.ex_date <= d1:  # an ex-date on a non-session day lands on the next bar
                expected *= a.factor
        if expected != 1:
            if abs(ratio / expected - 1) > tol:
                issues.append(
                    Issue("action_without_discontinuity", d1, f"expected x{expected:.4f}, saw x{ratio:.4f}")
                )
        elif abs(ratio - 1) > jump:
            issues.append(Issue("unexplained_jump", d1, f"close-to-close x{ratio:.4f}"))
    return issues
