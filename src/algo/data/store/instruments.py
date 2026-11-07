"""Instrument master repository. Nothing downstream keys on ticker strings; use instrument_id."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg


class NotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class Terms:
    lot_size: Decimal
    tick_size: Decimal
    qty_step: Decimal
    multiplier: Decimal
    margin_rule_version: str | None


class InstrumentRepo:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def _one(self, sql: str, args: tuple[Any, ...]) -> tuple[Any, ...]:
        row = self.conn.execute(sql, args).fetchone()
        assert row is not None
        return tuple(row)

    def add_exchange(self, mic: str, country: str, tz: str, currency: str, calendar_id: str) -> int:
        sql = (
            "INSERT INTO exchange (mic,country,timezone,currency,calendar_id) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING exchange_id"
        )
        return int(self._one(sql, (mic, country, tz, currency, calendar_id))[0])

    def add_instrument(
        self,
        exchange_id: int,
        symbol: str,
        asset_class: str = "equity",
        *,
        isin: str | None = None,
        quote_currency: str = "INR",
        listed_on: date | None = None,
        name: str | None = None,
    ) -> int:
        sql = (
            "INSERT INTO instrument "
            "(exchange_id,symbol,asset_class,isin,quote_currency,listed_on,name) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING instrument_id"
        )
        args = (exchange_id, symbol, asset_class, isin, quote_currency, listed_on, name)
        return int(self._one(sql, args)[0])

    def delist(self, instrument_id: int, on: date) -> None:
        self.conn.execute(
            "UPDATE instrument SET delisted_on=%s, status='delisted' WHERE instrument_id=%s",
            (on, instrument_id),
        )

    def add_terms(
        self,
        instrument_id: int,
        valid_from: date,
        valid_to: date | None,
        lot_size: Decimal,
        tick_size: Decimal,
        qty_step: Decimal,
        multiplier: Decimal = Decimal(1),
        margin_rule_version: str | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO instrument_terms VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (instrument_id, valid_from, valid_to, lot_size, tick_size, qty_step, multiplier,
             margin_rule_version),
        )  # fmt: skip

    def terms_as_of(self, instrument_id: int, d: date) -> Terms:
        row = self.conn.execute(
            "SELECT lot_size,tick_size,qty_step,multiplier,margin_rule_version "
            "FROM instrument_terms WHERE instrument_id=%s AND valid_from<=%s "
            "AND (valid_to IS NULL OR %s<valid_to)",
            (instrument_id, d, d),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no terms for instrument {instrument_id} on {d}")
        return Terms(*row)

    def add_alias(
        self,
        instrument_id: int,
        source: str,
        symbol: str,
        valid_from: date,
        valid_to: date | None = None,
        token: str | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO instrument_alias VALUES (%s,%s,%s,%s,%s,%s)",
            (instrument_id, source, symbol, token, valid_from, valid_to),
        )

    def resolve(self, source: str, symbol: str, d: date) -> int:
        row = self.conn.execute(
            "SELECT instrument_id FROM instrument_alias WHERE source=%s AND source_symbol=%s "
            "AND valid_from<=%s AND (valid_to IS NULL OR %s<valid_to)",
            (source, symbol, d, d),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"{source}:{symbol} unknown on {d}")
        return int(row[0])
