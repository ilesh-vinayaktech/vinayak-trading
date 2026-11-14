"""Adjustment factors. Raw prices are never edited; adjusted = raw * factor_on(bar_date).
factor_on(d) = product of factors of actions with ex_date > d (a bar ON the ex-date is already
post-action). Point-in-time: with as_of, only actions whose knowledge_time <= as_of count.
Factors are 28-digit Decimals (1/22 is not exact): compare with a tolerance, never ==.
Series: 'split' (split/bonus only: signals, charts) and 'total_return' (adds cash dividends)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

SPLIT_KINDS = ("bonus", "split")
PRICE_KINDS = ("resolved",)  # human-resolved price-only factors (demerger, rights, ...)


@dataclass(frozen=True)
class ActionRecord:
    ex_date: date
    kind: str
    status: str  # ok | review
    num: Decimal | None
    den: Decimal | None
    amount: Decimal | None
    knowledge_time: datetime
    provisional: bool = False  # estimated factor, not evidence-backed (research use only)


@dataclass(frozen=True)
class Adjustment:
    ex_date: date
    kind: str  # 'split' (bonus too, scales volume) | 'price' (price only) | 'dividend'
    factor: Decimal
    knowledge_time: datetime


@dataclass
class Built:
    adjustments: list[Adjustment]
    unapplied: list[ActionRecord]  # review-status or ambiguous: needs a human, NOT applied


def split_factor(num: Decimal, den: Decimal) -> Decimal:
    """Share multiplier num/den (bonus A:B => (A+B)/B; split X->Y => X/Y); price factor inverse."""
    if num <= 0 or den <= 0:
        raise ValueError("ratio must be positive")
    return den / num


def dividend_factor(amount: Decimal, prev_close: Decimal) -> Decimal:
    if not 0 < amount < prev_close:
        raise ValueError("dividend must be positive and below previous close")
    return 1 - amount / prev_close


def demerger_factor(
    child_per_parent: Decimal, child_price: Decimal, parent_prev_close: Decimal
) -> Decimal:
    """Parent keeps (1 - value handed out per parent share / cum price). Price only: the parent's
    share count does not change."""
    if child_per_parent <= 0 or child_price <= 0 or parent_prev_close <= 0:
        raise ValueError("ratio and prices must be positive")
    value = child_per_parent * child_price
    if value >= parent_prev_close:
        raise ValueError("demerged value must be below the parent's previous close")
    return 1 - value / parent_prev_close


def rights_factor(
    new: Decimal, held: Decimal, subscription_price: Decimal, prev_close: Decimal
) -> Decimal:
    """Theoretical ex-rights price / cum price. `new` new shares per `held` held (NSE A:B)."""
    if min(new, held, subscription_price, prev_close) <= 0:
        raise ValueError("ratio and prices must be positive")
    if subscription_price >= prev_close:
        raise ValueError("issue price at or above market: no adjustment, check the inputs")
    terp = (held * prev_close + new * subscription_price) / (held + new)
    return terp / prev_close


def build_adjustments(
    actions: Iterable[ActionRecord], prev_close_on: Callable[[date], Decimal]
) -> Built:
    """prev_close_on(ex_date) = raw close of the last session before ex_date (for dividends)."""
    adj: list[Adjustment] = []
    unapplied: list[ActionRecord] = []
    by_day_kind: dict[tuple[date, str], list[ActionRecord]] = defaultdict(list)
    for a in actions:
        if a.status != "ok" or a.kind not in (*SPLIT_KINDS, *PRICE_KINDS, "dividend"):
            unapplied.append(a)
        else:
            by_day_kind[(a.ex_date, a.kind)].append(a)
    for (day, kind), rows in sorted(by_day_kind.items()):
        kt = max(r.knowledge_time for r in rows)
        if kind == "dividend":  # several dividends on one ex-date act as one cash amount
            total = sum((r.amount or Decimal(0) for r in rows), Decimal(0))
            try:
                f = dividend_factor(total, prev_close_on(day))
            except (ValueError, LookupError):  # bad amount, or no bar before the ex-date
                unapplied.extend(rows)
                continue
            adj.append(Adjustment(day, "dividend", f, kt))
        elif len({(r.num, r.den) for r in rows}) > 1:  # e.g. a revised ratio next to the original
            unapplied.extend(rows)
        else:
            r = rows[0]
            if r.num is None or r.den is None:  # malformed record: a person must look at it
                unapplied.extend(rows)
                continue
            kind_out = "price" if kind in PRICE_KINDS else "split"
            adj.append(Adjustment(day, kind_out, split_factor(r.num, r.den), kt))
    return Built(adj, unapplied)


def factor_on(
    adjustments: Iterable[Adjustment],
    d: date,
    *,
    total_return: bool = False,
    volume: bool = False,
    as_of: datetime | None = None,
    applied_through: date | None = None,
    vendor_dividends: frozenset[date] = frozenset(),
) -> Decimal:
    """applied_through: the vendor (Kite) adjusted its history through this day. Measured against
    the raw NSE bars it applied every split and bonus, and rights and demergers by its own factor
    (the Kite series is the truth there), so all of those with ex_date <= this day are skipped.
    Dividends only when `vendor_dividends` lists their ex-date (see vendor_applied_dividends)."""
    f = Decimal(1)
    for a in adjustments:
        if a.ex_date <= d or (a.kind == "dividend" and not total_return):
            continue
        if volume and a.kind != "split":  # share count changes only with splits and bonuses
            continue
        if as_of is not None and a.knowledge_time > as_of:
            continue
        if applied_through is not None and a.kind != "dividend" and a.ex_date <= applied_through:
            continue
        if a.kind == "dividend" and a.ex_date in vendor_dividends:
            continue
        f *= a.factor
    return f


def vendor_applied_dividends(
    amounts: Mapping[date, Decimal], kite: Mapping[date, Decimal], raw: Mapping[date, Decimal]
) -> frozenset[date]:
    """Ex-dates whose cash dividend the vendor already took out of its history. The Kite/NSE close
    ratio steps across an ex-date by exactly the factor the vendor applied there, so a step of
    at least half the dividend yield below 1 means "applied". Not measurable (no common bar just
    before and just after) counts as not applied: true for 96% of dividends before 2025."""
    days = sorted(d for d in kite if d in raw)
    out = set()
    for ex, amount in amounts.items():
        before = [d for d in days if d < ex]
        after = [d for d in days if d >= ex]
        if not before or not after:
            continue
        b, a = before[-1], after[0]
        if (ex - b).days > 6 or (a - ex).days > 4:
            continue
        step = (kite[b] / raw[b]) / (kite[a] / raw[a])
        if step <= 1 - amount / raw[b] / 2:
            out.add(ex)
    return frozenset(out)
