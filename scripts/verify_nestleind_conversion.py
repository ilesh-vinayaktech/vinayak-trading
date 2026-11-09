# ruff: noqa: E501  (a report script)
"""READ-ONLY check of the ISIN-change conversion arithmetic on the REAL NESTLEIND prices around 4-5 Jan 2024.

A HYPOTHETICAL position (bought in memory at the 4 Jan close) is converted by an in-memory ledger at the real
ratio and marked at the real new-ISIN close of 5 Jan. Nothing is written to the database and no trade is
added to any dataset. It proves, on real data: quantity x10, cost basis unchanged, zero realised P&L and fees,
no cash movement, and that the change in wealth across the boundary equals EXACTLY the market move of the
price scale (no accounting residue); the ledger reconciles.
usage: verify_nestleind_conversion.py --db URL [--old 2653] [--new 1589] [--out docs/stage4/apply_proposals/nestleind_conversion_check.md]"""

import argparse
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from algo.data.reader import BarReader
from algo.ledger.ledger import Conversion, Ledger

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--old", type=int, default=2653)
ap.add_argument("--new", type=int, default=1589)
ap.add_argument(
    "--out", type=Path, default=Path("docs/stage4/apply_proposals/nestleind_conversion_check.md")
)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
CHANGE, BEFORE = date(2024, 1, 5), date(2024, 1, 4)
QTY = Decimal(100)
IST = ZoneInfo("Asia/Kolkata")


def close_on(reader, iid, day):
    return {b.ts.astimezone(IST).date(): b.close for b in reader.history(iid, day, day).bars}[day]


with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    rd = BarReader(c)
    old_close, new_close = close_on(rd, a.old, BEFORE), close_on(rd, a.new, CHANGE)

lg = Ledger(Decimal(10_000_000), date(2023, 12, 1))
lg.register_conversion(
    Conversion(
        a.old,
        a.new,
        CHANGE,
        Decimal(10),
        Decimal(1),
        "convert:real-check",
        True,
        ("NSE circular CML60084",),
        BEFORE,
        (CHANGE, "split"),
    )
)
lg.buy(BEFORE, a.old, QTY, old_close, Decimal(0), "trade:hypothetical-1")  # in memory only
cash_before, equity_before, cost_before = (
    lg.cash,
    lg.equity({a.old: old_close}),
    lg.cost_basis(a.old),
)
converted = lg.apply_conversion(CHANGE, a.old)
equity_after = lg.equity({a.new: new_close})
market_move = lg.qty(a.new) * new_close - QTY * old_close  # the only thing that may change wealth
pnl = lg.pnl({a.new: new_close})
checks = {
    "a position was converted": converted,
    "quantity x10": lg.qty(a.new) == QTY * 10 and lg.qty(a.old) == 0,
    "cost basis moved exactly": lg.cost_basis(a.new) == cost_before and lg.cost_basis(a.old) == 0,
    "no cash movement": lg.cash == cash_before,
    "zero realised P&L and fees": pnl.realized == 0 and pnl.fees == 0,
    "wealth change across 4-5 Jan equals the market move exactly": equity_after - equity_before
    == market_move,
    "unrealised P&L moved by the same amount": lg.unrealized({a.new: new_close}) == market_move,
    "the ledger reconciles": lg.reconcile({a.new: new_close}) == [],
}
ok = all(checks.values())
lines = [
    "# NESTLEIND conversion check on real prices (read-only; hypothetical position in memory)", "",
    f"- old ISIN close on {BEFORE}: {old_close}; new ISIN close on {CHANGE}: {new_close} (x10 = {new_close * 10})",
    f"- 100 old shares, cost {cost_before} (average {cost_before / QTY}) become {lg.qty(a.new)} new shares, cost {lg.cost_basis(a.new)} (average {lg.cost_basis(a.new) / lg.qty(a.new)})",
    f"- equity {equity_before} on {BEFORE} -> {equity_after} on {CHANGE}: change {equity_after - equity_before} = market move {market_move}", "",
    "| check | result |", "|---|---|",
    *[f"| {k} | {v} |" for k, v in checks.items()], "", f"**Result: {'PASS' if ok else 'FAIL'}**",
]  # fmt: skip
a.out.write_text("\n".join(lines) + "\n")
print("\n".join(lines))
raise SystemExit(0 if ok else 1)
