"""The corporate-action review queue as a worklist: unresolved items ranked by how much a wrong
(missing) adjustment could move prices we use, so reading time goes where it matters.

impact = base weight of the kind x 3 if the stock is in a Nifty 200 snapshot x (1 + 4 x the price
move across the ex-date, capped at 50%). Zero when there is no raw (NSE) bar before the ex-date:
nothing we hold can be adjusted (Kite's older candles look already adjusted: CANBK 2017 shows
about 52 where the exchange had 296). Read-only; resolving stays in algo.data.review.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

import psycopg

from algo.data.review import review_queue

# ponytail: hand-picked weights, tune once real decisions show which kinds hurt most.
BASE = {"demerger": 100, "split": 100, "bonus": 100, "rights": 60, "arrangement": 40,
        "other": 20, "buy": 10, "dividend": 5, "distribution": 1}  # fmt: skip
# ponytail: current-list snapshots only; switch to index_membership_event once that is loaded.
MEMBER_X = 3
MOVE_CAP = Decimal("0.5")


def impact(kind: str, move: Decimal | None, *, member: bool, has_prices: bool) -> int:
    if not has_prices:
        return 0
    jump = min(abs(move), MOVE_CAP) if move is not None else Decimal(0)
    return round(BASE.get(kind, BASE["other"]) * (MEMBER_X if member else 1) * (1 + 4 * jump))


def worklist(
    conn: psycopg.Connection, *, limit: int | None = None, kind: str | None = None
) -> dict[str, Any]:
    members = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT instrument_id FROM index_snapshot WHERE index_id='NIFTY200'"
        )
    }
    # Only NSE bars are raw; Kite candles (before the first NSE file) are already adjusted by Kite.
    raw_from = conn.execute(
        "SELECT min((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE source='nse'"
    ).fetchone()
    raw_start = raw_from[0] if raw_from else None
    rows: list[dict[str, Any]] = []
    for it in review_queue(conn):
        ratio = it.observed_ratio
        has_prices = it.prev_close is not None and raw_start is not None and it.ex_date > raw_start
        move = ratio - 1 if has_prices and ratio is not None else None
        member = it.instrument_id in members
        rows.append({
            "symbol": it.symbol, "ex_date": it.ex_date.isoformat(), "kind": it.kind,
            "subject": "; ".join(it.subjects), "reason": "; ".join(it.reasons),
            "prev_close": None if it.prev_close is None else str(it.prev_close),
            "ex_close": None if it.ex_close is None else str(it.ex_close),
            "move_pct": None if move is None else f"{move * 100:.2f}",
            "in_nifty200": member, "has_prices": has_prices,
            "impact": impact(it.kind, move, member=member, has_prices=has_prices),
        })  # fmt: skip
    rows.sort(key=lambda r: (-int(r["impact"]), str(r["symbol"]), str(r["ex_date"])))
    by_kind = dict(Counter(r["kind"] for r in rows))
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    return {"total": len(rows), "by_kind": by_kind, "items": rows[:limit]}
