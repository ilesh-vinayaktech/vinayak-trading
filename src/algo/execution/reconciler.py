# ruff: noqa: E501
"""What the reconciler compares besides orders (spec section 11): positions and cash. The broker is the truth; `compare` is pure, the
caller fetches both sides (the OMS's own fold of fills, or the ledger, against whatever the broker reports) and hands the differences
to `Oms.reconcile(extra=...)`, which records them and halts trading at its threshold."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from algo.execution.oms import Mismatch


@dataclass(frozen=True)
class Portfolio:
    positions: Mapping[int, int]  # instrument_id -> signed quantity
    cash: Decimal | None = None  # None: that side cannot say


def compare(
    ours: Portfolio,
    theirs: Portfolio,
    *,
    cash_tolerance: Decimal = Decimal(1),
    broker_may_hold_more: bool = False,
) -> list[Mismatch]:
    """Every instrument whose quantity differs (a missing one counts as 0), and the cash when both sides know it and it differs by more than `cash_tolerance` rupees.
    On an account that also holds shares bought by hand (`broker_may_hold_more`), the broker holding MORE than we do is expected and not reported;
    holding less is, because that means shares we bought are gone. Cash on such an account moves with the owner's own trades: pass None for it."""
    out = [
        Mismatch(
            "POSITION_MISMATCH",
            "",
            f"instrument {iid}: we hold {ours.positions.get(iid, 0)}, the broker {theirs.positions.get(iid, 0)}",
        )
        for iid in sorted({*ours.positions, *theirs.positions})
        if ours.positions.get(iid, 0) != theirs.positions.get(iid, 0)
        and not (broker_may_hold_more and theirs.positions.get(iid, 0) > ours.positions.get(iid, 0))
    ]
    if (
        ours.cash is not None
        and theirs.cash is not None
        and abs(ours.cash - theirs.cash) > cash_tolerance
    ):
        out.append(Mismatch("CASH_MISMATCH", "", f"we have {ours.cash}, the broker {theirs.cash}"))
    return out
