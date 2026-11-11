# ruff: noqa: E501
"""One paper account per user: settings (paper_account) and an append-only book (paper_event, migration 035).

Cash, positions and P&L are never stored. `load` replays the events through the Ledger the backtest engine uses, so the
arithmetic (fees, average cost, splits, dividends, reconciliation) is that same, already-tested code. Posting is
idempotent by `ref`. Corporate actions reach held shares once: splits and dividends are applied; anything the books
cannot value (rights, demergers, an unresolved action) is flagged and pauses the account (`attention`) rather than guessed.
UNVALIDATED research: nothing here can become live trading (the mode column only allows PAPER)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from algo.data.adjust.factors import ActionRecord
from algo.ledger.ledger import Ledger
from algo.paper.universe import UNIVERSES

COLUMNS = "user_id, strategy_id, params, enabled, mode, initial_cash, started_on, actions_through, attention, created_at, universe, max_instruments, timeframe"


class PaperError(ValueError):
    pass


SETTINGS = ("universe", "max_instruments", "timeframe", "params")


def _check_settings(universe: str, max_instruments: int | None, timeframe: str) -> None:
    if universe not in UNIVERSES:
        raise PaperError(f"unknown universe {universe!r}")
    if max_instruments is not None and not 5 <= max_instruments <= 500:
        raise PaperError("the instrument cap must be between 5 and 500")
    if timeframe != "1D":
        raise PaperError("only the daily timeframe is supported yet")


def create_account(
    conn: psycopg.Connection,
    user_id: UUID,
    *,
    strategy_id: str,
    params: Mapping[str, Any],
    initial_cash: Decimal,
    started_on: date,
    now: datetime,
    universe: str = "nifty200",
    max_instruments: int | None = None,
    timeframe: str = "1D",
) -> None:
    if initial_cash <= 0:
        raise PaperError("the starting cash must be positive")
    _check_settings(universe, max_instruments, timeframe)
    if get_account(conn, user_id) is not None:
        raise PaperError("this user already has a paper account")
    conn.execute(
        "INSERT INTO paper_account (user_id, strategy_id, params, initial_cash, started_on, actions_through, created_at, universe, max_instruments, timeframe) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            user_id,
            strategy_id,
            Jsonb(dict(params)),
            initial_cash,
            started_on,
            started_on,
            now,
            universe,
            max_instruments,
            timeframe,
        ),
    )


def get_account(conn: psycopg.Connection, user_id: UUID) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {COLUMNS} FROM paper_account WHERE user_id=%s", (user_id,)
    ).fetchone()
    return None if row is None else dict(zip(COLUMNS.split(", "), row, strict=True))


def _need(conn: psycopg.Connection, user_id: UUID) -> dict[str, Any]:
    acct = get_account(conn, user_id)
    if acct is None:
        raise PaperError("no paper account for this user")
    return acct


def set_enabled(conn: psycopg.Connection, user_id: UUID, enabled: bool) -> None:
    _need(conn, user_id)
    conn.execute("UPDATE paper_account SET enabled=%s WHERE user_id=%s", (enabled, user_id))


def update_settings(conn: psycopg.Connection, user_id: UUID, **changes: Any) -> None:
    """Change what the strategy runs on (universe, instrument cap, timeframe) or its parameters. Holdings the new settings
    no longer allow are sold by the strategy's next decision, not here."""
    acct = _need(conn, user_id)
    if set(changes) - set(SETTINGS):
        raise PaperError(f"{', '.join(sorted(set(changes) - set(SETTINGS)))} cannot be changed")
    new = {**acct, **changes}
    _check_settings(new["universe"], new["max_instruments"], new["timeframe"])
    conn.execute(
        "UPDATE paper_account SET universe=%s, max_instruments=%s, timeframe=%s, params=%s WHERE user_id=%s",
        (
            new["universe"],
            new["max_instruments"],
            new["timeframe"],
            Jsonb(dict(new["params"])),
            user_id,
        ),
    )


def clear_attention(conn: psycopg.Connection, user_id: UUID) -> None:
    _need(conn, user_id)
    conn.execute("UPDATE paper_account SET attention=NULL WHERE user_id=%s", (user_id,))


def _replay(
    ledger: Ledger,
    kind: str,
    day: date,
    iid: int,
    qty: Decimal | None,
    price: Decimal | None,
    commission: Decimal | None,
    charges: Any,
    num: Decimal | None,
    den: Decimal | None,
    amount: Decimal | None,
    note: str | None,
    ref: str,
) -> None:
    if kind in ("BUY", "SELL"):
        post = ledger.buy if kind == "BUY" else ledger.sell
        extra = [(str(t), Decimal(a)) for t, a in (charges or [])]
        post(
            day,
            iid,
            qty or Decimal(0),
            price or Decimal(0),
            commission or Decimal(0),
            ref,
            charges=extra,
        )
    elif kind == "SPLIT":
        ledger.apply_split(day, iid, num or Decimal(1), den or Decimal(1), ref)
    elif kind == "DIVIDEND":
        ledger.credit_dividend(day, iid, amount or Decimal(0), ref)
    else:
        ledger.flag_unmodelled(day, iid, note or "UNKNOWN", ref)


def load(conn: psycopg.Connection, user_id: UUID) -> Ledger:
    acct = _need(conn, user_id)
    ledger = Ledger(acct["initial_cash"], acct["started_on"])
    rows = conn.execute(
        "SELECT kind, day, instrument_id, qty, price, commission, charges, num, den, amount, note, ref FROM paper_event WHERE user_id=%s ORDER BY event_id",
        (user_id,),
    ).fetchall()
    for r in rows:
        _replay(ledger, *r)
    return ledger


def _insert(
    conn: psycopg.Connection,
    user_id: UUID,
    now: datetime,
    kind: str,
    day: date,
    iid: int,
    ref: str,
    **f: Any,
) -> bool:
    n = conn.execute(
        "INSERT INTO paper_event (user_id, day, kind, instrument_id, qty, price, commission, charges, num, den, amount, note, ref, created_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id, ref) DO NOTHING",
        (
            user_id,
            day,
            kind,
            iid,
            f.get("qty"),
            f.get("price"),
            f.get("commission"),
            Jsonb(f["charges"]) if "charges" in f else None,
            f.get("num"),
            f.get("den"),
            f.get("amount"),
            f.get("note"),
            ref,
            now,
        ),
    ).rowcount
    return bool(n)


def record_fill(
    conn: psycopg.Connection,
    user_id: UUID,
    *,
    day: date,
    side: str,
    iid: int,
    qty: Decimal,
    price: Decimal,
    commission: Decimal,
    charges: Sequence[tuple[str, Decimal]],
    ref: str,
    now: datetime,
) -> bool:
    """Book a simulated fill. False if this ref was already booked. A fill the account could not afford or does not hold is refused."""
    if side not in ("BUY", "SELL"):
        raise PaperError("side must be BUY or SELL")
    ledger = load(conn, user_id)
    extra = sum((a for _, a in charges), Decimal(0))
    if side == "BUY" and qty * price + commission + extra > ledger.cash:
        raise PaperError("not enough cash for this order")
    if side == "SELL" and qty > ledger.qty(iid):
        raise PaperError("you do not hold that many shares")
    return _insert(
        conn,
        user_id,
        now,
        side,
        day,
        iid,
        ref,
        qty=qty,
        price=price,
        commission=commission,
        charges=[[t, str(a)] for t, a in charges],
    )


def apply_actions(
    conn: psycopg.Connection,
    user_id: UUID,
    actions: Mapping[int, Sequence[ActionRecord]],
    *,
    through: date,
    now: datetime,
) -> int:
    """Apply corporate actions with ex-date after the account's `actions_through` and up to `through` to what is held.
    Returns how many were booked (each once, however often this is called)."""
    acct = _need(conn, user_id)
    lo = acct["actions_through"]
    ledger = load(conn, user_id)
    booked, notes = 0, []
    f: dict[str, Any]
    for iid in sorted(actions):
        for a in sorted(actions[iid], key=lambda r: r.ex_date):
            if ledger.qty(iid) == 0 or not lo < a.ex_date <= through:
                continue
            ref = f"action:{iid}:{a.ex_date}:{a.kind}:{a.num}:{a.den}:{a.amount}:{a.status}"
            if a.kind in ("bonus", "split") and a.status == "ok" and a.num and a.den:
                kind, f = "SPLIT", dict(num=a.num, den=a.den)
            elif a.kind == "dividend" and a.status == "ok" and a.amount:
                kind, f = "DIVIDEND", dict(amount=a.amount)
            else:
                kind, f = "UNMODELLED", dict(note=a.kind)
            if _insert(conn, user_id, now, kind, a.ex_date, iid, ref, **f):
                _replay(
                    ledger,
                    kind,
                    a.ex_date,
                    iid,
                    None,
                    None,
                    None,
                    None,
                    f.get("num"),
                    f.get("den"),
                    f.get("amount"),
                    f.get("note"),
                    ref,
                )
                booked += 1
                if kind == "UNMODELLED":
                    notes.append(f"{a.kind} (ex {a.ex_date}, instrument {iid}) needs review")
    attention = "; ".join(filter(None, [acct["attention"], *notes])) or None
    conn.execute(
        "UPDATE paper_account SET actions_through=%s, attention=%s WHERE user_id=%s",
        (max(lo, through), attention, user_id),
    )
    return booked
