# ruff: noqa: E501  (SQL statements and check labels are kept on one line each for review)
"""Move the history of one issuer from a single instrument onto two ISIN identities.

Before: one instrument holds everything (bars, corporate actions, terms, a symbol alias) although its
ISIN changed on `change`. After: an old-ISIN instrument owns what happened BEFORE `change`, the existing
instrument owns what happens from it, and a SAME_ISSUER_ISIN_CHANGE relationship links them. Nothing is
merged and no row is deleted; rows are only re-pointed.

Everything runs in ONE transaction and is checked before it commits: the counts must be conserved, no
instrument may own a row outside its interval, and the issuer-scoped read afterwards must equal the
read before in every adjustment mode (same closes, factors, volumes and adjustment version). Any failed
check rolls the whole thing back. `dry_run=True` performs every step and every check, then rolls back."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import psycopg

from algo.data.corporate_actions import records_for
from algo.data.issuer_series import IST
from algo.data.reader import BarReader, Loaded

MODES = ("none", "split", "total_return")
_DATED = {
    "bar_1d": "(ts AT TIME ZONE 'Asia/Kolkata')::date",
    "corporate_action": "ex_date",
    "action_resolution": "ex_date",
    "instrument_terms": "valid_from",
}


class MigrationError(Exception):
    pass


def _counts(conn: psycopg.Connection, iid: int, change: date) -> dict[str, tuple[int, int]]:
    """Per table: (rows owned, rows dated before `change`)."""
    out: dict[str, tuple[int, int]] = {}
    for table, col in _DATED.items():
        total, before = conn.execute(
            f"SELECT count(*), count(*) FILTER (WHERE {col} < %s) FROM {table} WHERE instrument_id=%s",  # noqa: S608
            (change, iid),
        ).fetchone()  # type: ignore[misc]
        out[table] = (total, before)
    return out


def _series(loaded: Loaded) -> dict[str, tuple[Any, ...]]:
    first, last = loaded.days[0], loaded.days[-1]
    out: dict[str, tuple[Any, ...]] = {}
    for mode in MODES:
        h = loaded.history(first, last, adjust=mode)
        out[mode] = (
            [b.close for b in h.bars],
            [b.factor for b in h.bars],
            [b.volume for b in h.bars],
            h.adjustment_version,
        )
    return out


def migrate_isin_change(
    conn: psycopg.Connection,
    *,
    new_id: int,
    old_isin: str,
    change: date,
    first_observed: date,
    evidence: list[str],
    decision_id: int,
    now: datetime,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Split instrument `new_id` at `change`. Returns the audit record (before, after, checks)."""
    row = conn.execute(
        "SELECT asset_class, exchange_id, symbol, isin, name, quote_currency FROM instrument"
        " WHERE instrument_id=%s",
        (new_id,),
    ).fetchone()
    if row is None:
        raise MigrationError(f"instrument {new_id} does not exist")
    asset, exch, symbol, new_isin, name, ccy = row
    if conn.execute(
        "SELECT 1 FROM corporate_action_relationship WHERE relationship_type='SAME_ISSUER_ISIN_CHANGE'"
        " AND target_instrument_id=%s AND effective_date=%s",
        (new_id, change),
    ).fetchone():
        return {"applied": False, "already_applied": True, "instrument_id": new_id}
    if old_isin == new_isin:
        raise MigrationError("the old and the new ISIN are the same")
    if conn.execute("SELECT 1 FROM instrument WHERE isin=%s", (old_isin,)).fetchone():
        raise MigrationError(f"an instrument with ISIN {old_isin} already exists")
    persisted = conn.execute(
        "SELECT (SELECT count(*) FROM backtest_trade WHERE instrument_id=%s AND day < %s),"
        " (SELECT count(*) FROM backtest_ledger WHERE instrument_id=%s AND day < %s)",
        (new_id, change, new_id, change),
    ).fetchone()
    if persisted and any(persisted):
        raise MigrationError(
            f"persisted backtest results hold {persisted[0]} trades and {persisted[1]} ledger lines "
            f"dated before {change} on instrument {new_id}: no execution may reference it before the change"
        )
    rd = BarReader(conn)
    rows = rd._raw(new_id)
    days = [r[0].astimezone(IST).date() for r in rows]
    pre_days, post_days = [d for d in days if d < change], [d for d in days if d >= change]
    if not pre_days or not post_days:
        raise MigrationError(
            f"instrument {new_id} needs bars on both sides of {change} to be split"
        )
    before_series = _series(Loaded(rows, records_for(conn, new_id), rd.visible_after, False))
    before = _counts(conn, new_id, change)
    audit: dict[str, Any] = {
        "instrument_id": new_id, "symbol": symbol, "change": str(change), "before": before,
    }  # fmt: skip
    with conn.transaction(force_rollback=dry_run):
        old_id = conn.execute(
            "INSERT INTO instrument (asset_class, exchange_id, symbol, isin, name, quote_currency, listed_on,"
            " delisted_on, status, first_observed_on, last_traded_on)"
            " VALUES (%s,%s,%s,%s,%s,%s,NULL,%s,'delisted',%s,%s) RETURNING instrument_id",
            (asset, exch, symbol, old_isin, name, ccy, change, first_observed, max(pre_days)),
        ).fetchone()[0]  # type: ignore[index]
        conn.execute(
            "UPDATE instrument SET first_observed_on=%s WHERE instrument_id=%s",
            (min(post_days), new_id),
        )
        # aliases: the new ISIN starts on the change date, the old one ends there: never an overlap
        conn.execute(
            "UPDATE instrument_alias SET valid_from=%s, valid_from_basis='EVIDENCED'"
            " WHERE instrument_id=%s AND source='nse' AND source_symbol=%s AND valid_from < %s",
            (change, new_id, symbol, change),
        )
        conn.execute(
            "INSERT INTO instrument_alias (instrument_id, source, source_symbol, valid_from, valid_from_basis,"
            " valid_to, valid_to_basis) VALUES (%s,'nse',%s,%s,'FIRST_OBSERVED',%s,'EVIDENCED')",
            (old_id, symbol, first_observed, change),
        )
        # terms: the old instrument inherits the terms in force before the change
        conn.execute(
            "INSERT INTO instrument_terms (instrument_id, valid_from, valid_to, lot_size, tick_size, qty_step,"
            " multiplier, margin_rule_version) SELECT %s, valid_from, %s, lot_size, tick_size, qty_step,"
            " multiplier, margin_rule_version FROM instrument_terms WHERE instrument_id=%s AND valid_from < %s",
            (old_id, change, new_id, change),
        )
        conn.execute(
            "UPDATE instrument_terms SET valid_from=%s WHERE instrument_id=%s AND valid_from < %s",
            (change, new_id, change),
        )
        conn.execute(
            "UPDATE bar_1d SET instrument_id=%s WHERE instrument_id=%s"
            " AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s",
            (old_id, new_id, change),
        )
        for table in ("corporate_action", "action_resolution"):
            conn.execute(
                f"UPDATE {table} SET instrument_id=%s WHERE instrument_id=%s AND ex_date < %s",  # noqa: S608
                (old_id, new_id, change),
            )
        conn.execute(
            "INSERT INTO corporate_action_relationship (relationship_type, source_instrument_id,"
            " target_instrument_id, target_symbol, effective_date, last_source_session, evidence,"
            " verification_status, review_decision_id, recorded_at)"
            " VALUES ('SAME_ISSUER_ISIN_CHANGE', %s, %s, %s, %s, %s, %s::jsonb, 'PROVISIONAL', %s, %s)",
            (old_id, new_id, symbol, change, max(pre_days), json.dumps(evidence), decision_id, now),
        )
        after_old, after_new = _counts(conn, old_id, change), _counts(conn, new_id, change)
        checks: dict[str, bool] = {}
        for t in ("bar_1d", "corporate_action", "action_resolution"):
            checks[f"{t}: nothing lost or duplicated"] = (
                after_old[t][0] + after_new[t][0] == before[t][0]
            )
            checks[f"{t}: the old instrument owns only rows before the change"] = (
                after_old[t][0] == after_old[t][1]
            )
            checks[f"{t}: the new instrument owns no row before the change"] = after_new[t][1] == 0
        checks["bars moved equal the bars that were dated before the change"] = (
            after_old["bar_1d"][0] == before["bar_1d"][1]
        )
        checks["terms: the old instrument inherited those that came before"] = (
            after_old["instrument_terms"][0] == before["instrument_terms"][1]
        )
        after_series = _series(rd.issuer_load(new_id))
        for mode in MODES:
            checks[f"issuer read equals the read before ({mode})"] = (
                after_series[mode] == before_series[mode]
            )
        audit |= {
            "old_instrument_id": old_id,
            "after_old": after_old,
            "after_new": after_new,
            "checks": checks,
        }
        failed = [k for k, v in checks.items() if not v]
        if failed:
            raise MigrationError("post-checks failed, rolled back: " + "; ".join(failed))
    audit["applied"] = not dry_run
    return audit
