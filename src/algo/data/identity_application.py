# ruff: noqa: E501  (SQL statements and the module docstring are kept readable)
"""Apply ONE reviewed KEEP_SEPARATE decision: a delisted historical instrument with its own ISIN and alias, plus one
effective-dated relationship to the surviving security. Never an alias onto the successor, never a membership transfer.

Refused (nothing written; the caller's transaction is untouched): no recorded KEEP_SEPARATE decision for the item, a target
that does not exist or whose ISIN is not the reviewed one, an ISIN that already has an instrument (so it is not re-applicable),
an alias that overlaps another or does not match the instrument, and an alias that ends before the last traded day."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class IdentityApplicationError(Exception):
    pass


@dataclass(frozen=True)
class AppliedIdentity:
    instrument_id: int
    relationship_id: int
    target_instrument_id: int


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def apply_historical_instrument(
    conn: psycopg.Connection,
    app: Mapping[str, Any],
    reviewed_targets: Mapping[str, str],
    now: datetime,
) -> AppliedIdentity:
    inst, alias, rel = app["instrument"], app["alias"], app["relationship"]
    with conn.transaction():
        decided = conn.execute(
            "SELECT 1 FROM review_decision WHERE decision_id=%s AND item_id=%s AND decision='KEEP_SEPARATE'",
            (app["decision_id"], app["item_id"]),
        ).fetchone()
        if decided is None:
            raise IdentityApplicationError(
                f"no KEEP_SEPARATE review decision {app['decision_id']} for {app['item_id']}"
            )
        sym = rel["target_symbol"]
        if sym not in reviewed_targets:
            raise IdentityApplicationError(f"target {sym} is not in the reviewed targets")
        target = conn.execute(
            "SELECT instrument_id, isin, exchange_id, quote_currency FROM instrument WHERE symbol=%s",
            (sym,),
        ).fetchone()
        if target is None:
            raise IdentityApplicationError(f"target {sym} does not exist")
        if target[1] != reviewed_targets[sym]:
            raise IdentityApplicationError(
                f"target {sym} has ISIN {target[1]} which is not the reviewed {reviewed_targets[sym]}"
            )
        if conn.execute("SELECT 1 FROM instrument WHERE isin=%s", (inst["isin"],)).fetchone():
            raise IdentityApplicationError(f"ISIN {inst['isin']} already has an instrument")
        if alias["source_symbol"] != inst["symbol"]:
            raise IdentityApplicationError("alias symbol must equal the instrument symbol")
        valid_from, valid_to, last = (
            _d(alias["valid_from"]),
            _d(alias["valid_to"]),
            _d(inst["last_traded_on"]),
        )
        if last is not None and valid_to is not None and valid_to <= last:
            raise IdentityApplicationError("alias must end after the last traded day")
        clash = conn.execute(
            "SELECT 1 FROM instrument_alias WHERE source=%s AND source_symbol=%s"
            " AND daterange(valid_from, valid_to, '[)') && daterange(%s, %s, '[)')",
            (alias["source"], alias["source_symbol"], valid_from, valid_to),
        ).fetchone()
        if clash:
            raise IdentityApplicationError(
                f"alias {alias['source']}:{alias['source_symbol']} overlaps an existing alias"
            )
        iid = conn.execute(
            "INSERT INTO instrument (asset_class, exchange_id, symbol, isin, name, quote_currency, listed_on,"
            " delisted_on, status, first_observed_on, last_traded_on)"
            " VALUES ('equity',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING instrument_id",
            (target[2], inst["symbol"], inst["isin"], app["name"], target[3], _d(inst["listed_on"]),
             _d(inst["delisted_on"]), inst["status"], _d(inst["first_observed_on"]), last),
        ).fetchone()[0]  # type: ignore[index]  # fmt: skip
        conn.execute(
            "INSERT INTO instrument_alias (instrument_id, source, source_symbol, valid_from, valid_from_basis,"
            " valid_to, valid_to_basis) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (iid, alias["source"], alias["source_symbol"], valid_from, alias["valid_from_basis"], valid_to,
             alias["valid_to_basis"]),
        )  # fmt: skip
        rid = conn.execute(
            "INSERT INTO corporate_action_relationship (relationship_type, source_instrument_id,"
            " target_instrument_id, target_symbol, appointed_date, effective_date, last_source_session,"
            " ratio_num, ratio_den, known_at, evidence, verification_status, review_decision_id, recorded_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING relationship_id",
            (rel["relationship_type"], iid, target[0], sym, _d(rel["appointed_date"]), _d(rel["effective_date"]),
             last, rel["ratio_num"], rel["ratio_den"], _d(rel["known_at"]), Jsonb(rel["evidence"]),
             rel["verification_status"], rel["review_decision_id"], now),
        ).fetchone()[0]  # type: ignore[index]  # fmt: skip
    return AppliedIdentity(int(iid), int(rid), int(target[0]))
