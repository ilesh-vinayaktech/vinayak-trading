# ruff: noqa: E501
"""A fingerprint of the data a backtest read, as the database held it at a chosen moment.

A run pinned to `known_at` ignores bars, corporate actions and decisions ingested after that moment, so when a provider later
corrects history the same run still reads what it read before. The fingerprint covers every input of that read: the daily
bars (latest version per day as of the pin), the corporate actions and the human decisions about them. It is stable for the
same inputs, independent of the order instruments are given in, and changes if any input changes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime

import psycopg

from algo.core.clock import require_utc

BARS = """
SELECT encode(sha256(convert_to(coalesce(string_agg(format('%%s|%%s|%%s|%%s|%%s|%%s|%%s|%%s', ts, open, high, low, close,
       volume, coalesce(adjusted_through::text, ''), dataset_version), E'\\n' ORDER BY ts), ''), 'UTF8')), 'hex')
FROM (SELECT DISTINCT ON (ts) * FROM bar_1d WHERE instrument_id=%s AND source=%s AND ingested_at <= %s
      ORDER BY ts, dataset_version DESC) b
"""
ACTIONS = """
SELECT encode(sha256(convert_to(coalesce(string_agg(format('%%s|%%s|%%s|%%s|%%s|%%s|%%s', ex_date, kind, status, num, den,
       amount, knowledge_time), E'\\n' ORDER BY ex_date, kind, id), ''), 'UTF8')), 'hex')
FROM corporate_action WHERE instrument_id=%s AND ingested_at <= %s
"""
DECISIONS = """
SELECT encode(sha256(convert_to(coalesce(string_agg(format('%%s|%%s|%%s|%%s|%%s', ex_date, kind, treatment, factor,
       resolved_at), E'\\n' ORDER BY id), ''), 'UTF8')), 'hex')
FROM action_resolution WHERE instrument_id=%s AND resolved_at <= %s
"""


def _one(conn: psycopg.Connection, sql: str, *args: object) -> str:
    row = conn.execute(sql, args).fetchone()
    assert row is not None
    return str(row[0])


def snapshot_hash(
    conn: psycopg.Connection, source: str, instrument_ids: Sequence[int], known_at: datetime
) -> str:
    at = require_utc(known_at)
    parts = {}
    for iid in sorted(set(instrument_ids)):
        parts[str(iid)] = [
            _one(conn, BARS, iid, source, at),
            _one(conn, ACTIONS, iid, at),
            _one(conn, DECISIONS, iid, at),
        ]
    return hashlib.sha256(json.dumps([source, parts], sort_keys=True).encode()).hexdigest()
