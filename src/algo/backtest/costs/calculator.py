# ruff: noqa: E501
"""Trade-level charge calculation. Pure: (schedule, side, qty, price) -> itemised charges.
Every line says what it was computed from, so each rupee deducted can be explained and traced to a
schedule version and a source document. Rounding is applied per component, per executed order,
half-up to the paisa unless the component says otherwise."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from algo.backtest.costs.schedule import Basis, Component, Schedule, Side

PAISA = Decimal("0.01")
HUNDRED = Decimal(100)


@dataclass(frozen=True)
class ChargeLine:
    type: str
    amount: Decimal  # rupees deducted (after rounding)
    basis_value: Decimal | None  # the value the rate applied to (trade value / GST base)
    formula: str  # human-readable derivation
    rounding: str
    source: str  # source key in the schedule
    evidence: str = ""  # what the component's rate rests on (VERIFIED, ASSUMED ...); empty for a flat-bps placeholder


@dataclass(frozen=True)
class Charges:
    side: str
    schedule_id: str
    schedule_version: str
    schedule_status: str
    lines: tuple[ChargeLine, ...]

    @property
    def total(self) -> Decimal:
        return sum((ln.amount for ln in self.lines), Decimal(0))

    def amount(self, type_: str) -> Decimal:
        return sum((ln.amount for ln in self.lines if ln.type == type_), Decimal(0))

    @property
    def unevidenced(self) -> tuple[str, ...]:
        """Component types whose rate is an assumption or unavailable: a run that used them says so."""
        return tuple(
            sorted({ln.type for ln in self.lines if ln.evidence in ("ASSUMED", "UNAVAILABLE")})
        )


def _round(x: Decimal, how: str) -> Decimal:
    return x.quantize(PAISA, rounding=ROUND_HALF_UP) if how == "HALF_UP_2DP" else x


def _applies(c: Component, side: str) -> bool:
    return c.side is Side.BOTH or c.side.value == side


def _raw(c: Component, value: Decimal) -> tuple[Decimal, str]:
    if c.basis is Basis.TRADE_VALUE:
        assert c.rate_pct is not None
        raw, formula = value * c.rate_pct / HUNDRED, f"{c.rate_pct}% of {value}"
        if c.minimum is not None and raw < c.minimum:
            raw, formula = c.minimum, f"{formula}, raised to minimum {c.minimum}"
        if c.maximum is not None and raw > c.maximum:
            raw, formula = c.maximum, f"{formula}, capped at maximum {c.maximum}"
        return raw, formula
    assert c.amount is not None
    unit = "per executed order" if c.basis is Basis.PER_EXECUTED_ORDER else "per scrip"
    return c.amount, f"flat {c.amount} {unit}"


def compute_charges(
    schedule: Schedule, side: str, qty: Decimal, price: Decimal, *, dp_already_charged: bool = False
) -> Charges:
    """Charges for ONE executed order of `qty` shares at `price` on the BUY or SELL side.

    The depository charge is levied once per scrip per day on which shares are debited from the demat account, whatever the number of
    sell orders or fills. The caller, which knows what was already charged that day for that scrip, says so with `dp_already_charged`:
    the line is then kept (so the schedule's coverage stays visible) but costs nothing."""
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if qty <= 0 or price <= 0:
        raise ValueError("qty and price must be positive")
    value = qty * price
    lines: list[ChargeLine] = []
    gst_base = Decimal(0)
    for c in schedule.components:
        if not _applies(c, side):
            continue
        if c.basis is Basis.GST_BASE:
            assert c.rate_pct is not None
            amount = _round(gst_base * c.rate_pct / HUNDRED, c.rounding)
            lines.append(
                ChargeLine(
                    c.type,
                    amount,
                    gst_base,
                    f"{c.rate_pct}% of GST base {gst_base}",
                    c.rounding,
                    c.source,
                    c.evidence,
                )
            )
            continue
        raw, formula = _raw(c, value)
        if c.type == "DP_CHARGE" and dp_already_charged:
            raw, formula = Decimal(0), "already charged for this scrip on this debit day"
        amount = _round(raw, c.rounding)
        if c.taxable_for_gst:
            gst_base += amount
        lines.append(
            ChargeLine(
                c.type,
                amount,
                value if c.basis is Basis.TRADE_VALUE else None,
                formula,
                c.rounding,
                c.source,
                c.evidence,
            )
        )
    return Charges(side, schedule.id, schedule.version, schedule.status, tuple(lines))


def contract_note_shortfall(schedule: Schedule, brokerage_total: Decimal) -> Decimal:
    """Delivery contract notes carry a minimum brokerage: the extra rupees needed to reach it
    (0 when there is no minimum or it is already met)."""
    floor = schedule.contract_note_min_brokerage
    if floor is None or brokerage_total >= floor:
        return Decimal(0)
    return floor - brokerage_total
