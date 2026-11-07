"""Event-sourced financial ledger: the ONE source of truth for cash, positions, fees and P&L.

Every movement is an immutable, numbered entry that cites its source event (`ref`), e.g.
`trade:5` or `action:12:2025-06-06:bonus:0`. A source event can be booked once. Long-only,
average-cost accounting; fees are kept apart from P&L on the price.

  ledger     kind          meaning
  cash       INITIAL/BUY/SELL/FEE/DIVIDEND   cash movements (signed)
  position   BUY/SELL/SPLIT                  qty delta; amount = cost basis delta
  fee        COMMISSION                      fee paid (positive)
  pnl        REALIZED                        realized P&L on a sale (price result, before fees)
  event      UNMODELLED:<kind>               an action the accounting cannot value (flagged)

`reconcile()` re-derives every balance from the entries alone and cross-checks each trade's cash,
position, fee and P&L entries against each other; any disagreement is returned, never hidden.
Identity (from entries alone): (cash - initial) + cost basis - realized - dividends + fees = 0.
With prices, also: equity - initial = realized + unrealized + dividends - fees.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

TOL = Decimal("1e-9")  # rupees: average-cost division leaves 28-digit residue at worst


class LedgerError(Exception):
    pass


class DuplicateBooking(LedgerError):
    pass


class InsufficientCash(LedgerError):
    pass


class InsufficientPosition(LedgerError):
    pass


@dataclass(frozen=True)
class Entry:
    seq: int
    day: date
    ledger: str
    kind: str
    instrument_id: int | None
    qty: Decimal
    amount: Decimal
    ref: str


@dataclass(frozen=True)
class PnL:
    realized: Decimal
    unrealized: Decimal
    dividends: Decimal
    fees: Decimal

    @property
    def net(self) -> Decimal:
        return self.realized + self.unrealized + self.dividends - self.fees


class Ledger:
    def __init__(self, initial_cash: Decimal, day: date) -> None:
        if initial_cash < 0:
            raise ValueError("initial cash cannot be negative")
        self.initial_cash = initial_cash
        self.entries: list[Entry] = []
        self._cash = Decimal(0)
        self._qty: dict[int, Decimal] = defaultdict(Decimal)
        self._cost: dict[int, Decimal] = defaultdict(Decimal)
        self._realized = self._dividends = self._fees = Decimal(0)
        self._fees_by: dict[str, Decimal] = defaultdict(Decimal)
        self._booked: set[str] = set()
        self._add(day, "cash", "INITIAL", None, Decimal(0), initial_cash, "initial")
        self._booked.add("initial")

    # ---- state -------------------------------------------------------------------------------
    @property
    def cash(self) -> Decimal:
        return self._cash

    def qty(self, instrument_id: int) -> Decimal:
        return self._qty.get(instrument_id, Decimal(0))

    def quantities(self) -> dict[int, Decimal]:
        return {i: q for i, q in self._qty.items() if q != 0}

    def cost_basis(self, instrument_id: int) -> Decimal:
        return self._cost.get(instrument_id, Decimal(0))

    def unmodelled(self) -> list[Entry]:
        return [e for e in self.entries if e.ledger == "event"]

    def _add(
        self,
        day: date,
        ledger: str,
        kind: str,
        iid: int | None,
        qty: Decimal,
        amount: Decimal,
        ref: str,
    ) -> None:
        self.entries.append(Entry(len(self.entries) + 1, day, ledger, kind, iid, qty, amount, ref))
        if ledger == "cash":
            self._cash += amount
            if kind == "DIVIDEND":
                self._dividends += amount
        elif ledger == "position":
            assert iid is not None
            self._qty[iid] += qty
            self._cost[iid] += amount
        elif ledger == "fee":
            self._fees += amount
            self._fees_by[kind] += amount
        elif ledger == "pnl":
            self._realized += amount

    def _book(self, ref: str) -> None:
        if ref in self._booked:
            raise DuplicateBooking(f"source event {ref} is already booked")
        self._booked.add(ref)

    # ---- postings ----------------------------------------------------------------------------
    def buy(
        self,
        day: date,
        iid: int,
        qty: Decimal,
        price: Decimal,
        fee: Decimal,
        ref: str,
        *,
        charges: Sequence[tuple[str, Decimal]] = (),
    ) -> None:
        """`fee` is a single commission; `charges` are itemised (type, amount) lines, each booked as
        its own fee entry with its own matching cash entry."""
        if qty <= 0 or price <= 0 or fee < 0:
            raise ValueError("buy needs qty > 0, price > 0, fee >= 0")
        extra = self._check_charges(charges)
        value = qty * price
        if value + fee + extra > self._cash + TOL:
            raise InsufficientCash(f"need {value + fee + extra}, have {self._cash}")
        self._book(ref)
        self._add(day, "position", "BUY", iid, qty, value, ref)
        self._add(day, "cash", "BUY", iid, Decimal(0), -value, ref)
        self._fee(day, iid, fee, charges, ref)

    def sell(
        self,
        day: date,
        iid: int,
        qty: Decimal,
        price: Decimal,
        fee: Decimal,
        ref: str,
        *,
        charges: Sequence[tuple[str, Decimal]] = (),
    ) -> None:
        if qty <= 0 or price <= 0 or fee < 0:
            raise ValueError("sell needs qty > 0, price > 0, fee >= 0")
        self._check_charges(charges)
        held = self.qty(iid)
        if qty > held:
            raise InsufficientPosition(f"selling {qty} of {iid} but holding {held}")
        self._book(ref)
        cost = self._cost[iid]
        removed = cost if qty == held else cost * qty / held  # a full exit clears the basis exactly
        proceeds = qty * price
        self._add(day, "position", "SELL", iid, -qty, -removed, ref)
        self._add(day, "cash", "SELL", iid, Decimal(0), proceeds, ref)
        self._add(day, "pnl", "REALIZED", iid, Decimal(0), proceeds - removed, ref)
        self._fee(day, iid, fee, charges, ref)

    @staticmethod
    def _check_charges(charges: Sequence[tuple[str, Decimal]]) -> Decimal:
        kinds = [k for k, _ in charges]
        if len(set(kinds)) != len(kinds) or "COMMISSION" in kinds:
            raise ValueError("charge types must be distinct and not COMMISSION")
        if any(a < 0 for _, a in charges):
            raise ValueError("charges cannot be negative")
        return sum((a for _, a in charges), Decimal(0))

    def _fee(
        self, day: date, iid: int, fee: Decimal, charges: Sequence[tuple[str, Decimal]], ref: str
    ) -> None:
        if fee > 0:
            self._add(day, "fee", "COMMISSION", iid, Decimal(0), fee, ref)
            self._add(day, "cash", "FEE", iid, Decimal(0), -fee, ref)
        for kind, amount in charges:
            if amount > 0:
                self._add(day, "fee", kind, iid, Decimal(0), amount, ref)
                self._add(day, "cash", f"FEE:{kind}", iid, Decimal(0), -amount, ref)

    def post_charges(self, day: date, charges: Sequence[tuple[str, Decimal]], ref: str) -> None:
        """Charges not tied to one trade (e.g. a contract-note-level top-up)."""
        extra = self._check_charges(charges)
        if extra <= 0:
            raise ValueError("nothing to charge")
        if extra > self._cash + TOL:
            raise InsufficientCash(f"need {extra}, have {self._cash}")
        self._book(ref)
        for kind, amount in charges:
            if amount > 0:
                self._add(day, "fee", kind, None, Decimal(0), amount, ref)
                self._add(day, "cash", f"FEE:{kind}", None, Decimal(0), -amount, ref)

    def fee_breakdown(self) -> dict[str, Decimal]:
        """Fees paid so far, by type (COMMISSION, STT, STAMP_DUTY, ...)."""
        return {k: v for k, v in sorted(self._fees_by.items()) if v != 0}

    def apply_split(self, day: date, iid: int, num: Decimal, den: Decimal, ref: str) -> None:
        """Bonus / split: share count x num/den, total cost unchanged (average cost falls)."""
        if num <= 0 or den <= 0:
            raise ValueError("split ratio must be positive")
        held = self.qty(iid)
        if held == 0:
            raise ValueError("nothing held to adjust")
        self._book(ref)
        self._add(day, "position", "SPLIT", iid, held * num / den - held, Decimal(0), ref)

    def credit_dividend(self, day: date, iid: int, per_share: Decimal, ref: str) -> Decimal:
        if per_share <= 0:
            raise ValueError("dividend per share must be positive")
        held = self.qty(iid)
        if held == 0:
            raise ValueError("nothing held to receive a dividend")
        self._book(ref)
        amount = held * per_share
        self._add(day, "cash", "DIVIDEND", iid, held, amount, ref)
        return amount

    def flag_unmodelled(self, day: date, iid: int, kind: str, ref: str) -> None:
        """Held through an action this accounting cannot value (demerger child shares, rights)."""
        self._book(ref)
        self._add(day, "event", f"UNMODELLED:{kind}", iid, self.qty(iid), Decimal(0), ref)

    # ---- valuation ---------------------------------------------------------------------------
    def _price(self, prices: Mapping[int, Decimal], iid: int) -> Decimal:
        if iid not in prices:
            raise LookupError(f"no price for held instrument {iid}")
        return prices[iid]

    def equity(self, prices: Mapping[int, Decimal]) -> Decimal:
        return self._cash + sum(
            (q * self._price(prices, i) for i, q in self._qty.items() if q != 0), Decimal(0)
        )

    def unrealized(self, prices: Mapping[int, Decimal]) -> Decimal:
        return sum(
            (q * self._price(prices, i) - self._cost[i] for i, q in self._qty.items() if q != 0),
            Decimal(0),
        )

    def pnl(self, prices: Mapping[int, Decimal]) -> PnL:
        return PnL(self._realized, self.unrealized(prices), self._dividends, self._fees)

    # ---- reconciliation ----------------------------------------------------------------------
    def reconcile(self, prices: Mapping[int, Decimal] | None = None) -> list[str]:
        """Re-derive everything from `entries` alone. Empty list = the books agree."""
        out: list[str] = []
        cash, qty, cost, realized, dividends, fees, initial = self._replay(out)
        if abs(initial - self.initial_cash) > TOL:
            out.append(f"initial cash: stated {self.initial_cash} != entries {initial}")
        if abs(cash - self._cash) > TOL:
            out.append(f"cash: running {self._cash} != entries {cash}")
        zero = Decimal(0)
        for iid in sorted(set(qty) | set(self._qty)):
            q_entries, q_running = qty.get(iid, zero), self._qty.get(iid, zero)
            c_entries, c_running = cost.get(iid, zero), self._cost.get(iid, zero)
            if abs(q_entries - q_running) > TOL:
                out.append(f"position {iid}: running {q_running} != entries {q_entries}")
            if abs(c_entries - c_running) > TOL:
                out.append(f"cost basis {iid}: running {c_running} != entries {c_entries}")
            if q_entries < -TOL:
                out.append(f"position {iid} is negative: {q_entries}")
            if abs(q_entries) <= TOL and abs(c_entries) > TOL:
                out.append(f"cost basis {iid} remains ({c_entries}) with no shares")
        for name, ours, theirs in (
            ("realized", self._realized, realized),
            ("dividends", self._dividends, dividends),
            ("fees", self._fees, fees),
        ):
            if abs(ours - theirs) > TOL:
                out.append(f"{name}: running {ours} != entries {theirs}")
        by_kind: dict[str, Decimal] = defaultdict(Decimal)
        for e in self.entries:
            if e.ledger == "fee":
                by_kind[e.kind] += e.amount
        for kind in sorted(set(by_kind) | set(self._fees_by)):
            ours, theirs = self._fees_by.get(kind, zero), by_kind.get(kind, zero)
            if abs(ours - theirs) > TOL:
                out.append(f"fees[{kind}]: running {ours} != entries {theirs}")
        # Accounting identity from the entries alone (prices cancel out of it):
        #   (cash - initial) + cost basis - realized - dividends + fees == 0
        identity = (cash - initial) + sum(cost.values(), Decimal(0)) - realized - dividends + fees
        if abs(identity) > TOL:
            out.append(
                f"identity broken: cash movements, cost basis and P&L disagree by {identity}"
            )
        if prices is not None:  # the valuation functions must agree with the entries' P&L
            gap = self.equity(prices) - self.initial_cash - self.pnl(prices).net
            if abs(gap) > TOL:
                out.append(f"valuation: equity - initial != net P&L by {gap}")
        return out

    def _replay(
        self, problems: list[str]
    ) -> tuple[Decimal, dict[int, Decimal], dict[int, Decimal], Decimal, Decimal, Decimal, Decimal]:
        cash = realized = dividends = fees = initial = Decimal(0)
        qty: dict[int, Decimal] = defaultdict(Decimal)
        cost: dict[int, Decimal] = defaultdict(Decimal)
        seen: set[tuple[str, str, str]] = set()
        by_ref: dict[str, dict[tuple[str, str], Entry]] = defaultdict(dict)
        for n, e in enumerate(self.entries, 1):
            if e.seq != n:
                problems.append(f"entry numbering: position {n} has seq {e.seq}")
            key = (e.ledger, e.kind, e.ref)
            if key in seen:
                problems.append(f"duplicate booking of {e.ledger}/{e.kind} for {e.ref}")
            seen.add(key)
            by_ref[e.ref][(e.ledger, e.kind)] = e
            if e.ledger == "cash":
                cash += e.amount
                dividends += e.amount if e.kind == "DIVIDEND" else Decimal(0)
                initial += e.amount if e.kind == "INITIAL" else Decimal(0)
            elif e.ledger == "position" and e.instrument_id is not None:
                qty[e.instrument_id] += e.qty
                cost[e.instrument_id] += e.amount
            elif e.ledger == "fee":
                fees += e.amount
            elif e.ledger == "pnl":
                realized += e.amount
        for ref, group in by_ref.items():
            self._check_trade(ref, group, problems)
        return cash, qty, cost, realized, dividends, fees, initial

    @staticmethod
    def _check_trade(ref: str, g: dict[tuple[str, str], Entry], problems: list[str]) -> None:
        buy_pos, buy_cash = g.get(("position", "BUY")), g.get(("cash", "BUY"))
        sell_pos, sell_cash = g.get(("position", "SELL")), g.get(("cash", "SELL"))
        real = g.get(("pnl", "REALIZED"))
        if (buy_pos is None) != (buy_cash is None):
            problems.append(f"{ref}: BUY needs both a position and a cash entry")
        elif buy_pos and buy_cash and abs(buy_pos.amount + buy_cash.amount) > TOL:
            problems.append(f"{ref}: BUY cash {buy_cash.amount} != cost {buy_pos.amount}")
        if (sell_pos is None) != (sell_cash is None) or (sell_pos is None) != (real is None):
            problems.append(f"{ref}: SELL needs position, cash and realized-P&L entries")
        elif (
            sell_pos
            and sell_cash
            and real
            and abs(real.amount - (sell_cash.amount + sell_pos.amount)) > TOL
        ):
            problems.append(f"{ref}: realized {real.amount} != proceeds - cost removed")
        fee_kinds = {k for (lg, k) in g if lg == "fee"} | {
            "COMMISSION" if k == "FEE" else k[4:]
            for (lg, k) in g
            if lg == "cash" and (k == "FEE" or k.startswith("FEE:"))
        }
        for kind in sorted(fee_kinds):
            fee = g.get(("fee", kind))
            fee_cash = g.get(("cash", "FEE" if kind == "COMMISSION" else f"FEE:{kind}"))
            label = "fee" if kind == "COMMISSION" else f"{kind} fee"
            if (fee is None) != (fee_cash is None):
                problems.append(f"{ref}: a {label} needs both a fee and a cash entry")
            elif fee and fee_cash and abs(fee.amount + fee_cash.amount) > TOL:
                problems.append(f"{ref}: {label} {fee.amount} != cash paid {-fee_cash.amount}")
