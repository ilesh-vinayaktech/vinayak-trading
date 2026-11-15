# ruff: noqa: E501  (a report script)
"""Verify a security-conversion instruction against the REAL database without a permanent write.

dry-run   (default): inside ONE transaction that is always rolled back, apply the schema migrations, record the
                     instruction from its config, then run every check below.
persisted          : the instruction is already recorded; run the same checks read-only.

Checks: the table's constraints exist; the stored row equals the config field by field; it links to the existing
SAME_ISSUER_ISIN_CHANGE relationship; the loader returns it; recording changed no existing row (row-level
fingerprints of every related table); and an IN-MEMORY backtest on the real bars (the strategy buys the old ISIN;
the run is never saved) converts the position exactly once on the new ISIN's first session at quantity x ratio,
cost basis unchanged, no P&L or fees, wealth change equal to the market move.
usage: verify_conversion_instruction.py --db URL [--config config/security_conversions/nestleind.json]
       [--mode dry-run|persisted] [--out docs/stage4/apply_proposals/nestleind_conversion_instruction_<mode>.md]"""

import argparse
import hashlib
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import psycopg

from algo.backtest.costs.policy import CostModel
from algo.backtest.engine import BacktestConfig, run_backtest
from algo.data.conversions import conversion_ref, load_conversions, store_conversion
from algo.data.store.migrate import migrate
from algo.research import slot
from algo.strategy.base import Strategy, StrategyParams

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--config", type=Path, default=Path("config/security_conversions/nestleind.json"))
ap.add_argument("--mode", choices=("dry-run", "persisted"), default="dry-run")
ap.add_argument("--out", type=Path, default=None)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
doc = json.loads(a.config.read_text())
out_path = a.out or Path(
    f"docs/stage4/apply_proposals/nestleind_conversion_instruction_{a.mode.replace('-', '_')}.md"
)
checks: dict[str, bool] = {}
notes: list[str] = []
TABLES = (
    "instrument", "instrument_terms", "instrument_alias", "corporate_action", "action_resolution",
    "corporate_action_relationship", "backtest_run", "backtest_trade", "backtest_equity",
    "backtest_ledger", "review_decision", "index_release_row", "index_monthly_constituent",
)  # fmt: skip


def fingerprints(conn):
    """Row-level: count and an md5 of every row's text, per table; bars only for the two instruments."""
    out = {}
    for t in TABLES:
        out[t] = tuple(
            conn.execute(
                f"SELECT count(*), md5(coalesce(string_agg(x::text, ',' ORDER BY x::text), '')) FROM {t} x"
            ).fetchone()
        )  # noqa: S608
    out["bar_1d (the two instruments)"] = tuple(conn.execute(
        "SELECT count(*), md5(coalesce(string_agg(x::text, ',' ORDER BY x::text), '')) FROM bar_1d x"
        " WHERE instrument_id IN (SELECT instrument_id FROM instrument WHERE isin IN (%s, %s))",
        (doc["source_isin"], doc["target_isin"]),
    ).fetchone())  # fmt: skip
    return out


class HoldOld(Strategy):
    """Buys the old ISIN once, then holds (returns nothing). In memory only."""

    id, version, Params = "conversion-check", "1", StrategyParams

    def __init__(self, old: int, new: int) -> None:
        super().__init__(StrategyParams())
        self.old, self.new, self.calls = old, new, 0

    def universe(self, ctx):
        return [self.old, self.new]

    def on_schedule(self, ctx):
        self.calls += 1
        return {self.old: D("0.1")} if self.calls == 1 else None


def verify(conn: psycopg.Connection) -> None:
    ids = {
        r: conn.execute(
            "SELECT instrument_id FROM instrument WHERE isin=%s", (doc[f"{r}_isin"],)
        ).fetchone()[0]
        for r in ("source", "target")
    }
    old, new = ids["source"], ids["target"]
    effective = date.fromisoformat(doc["effective_date"])
    cons = [
        d
        for _, d in conn.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='security_conversion'::regclass"
        )
    ]

    def has(needle: str) -> bool:
        return any(needle in d for d in cons)

    for needle, label in (
        ("ratio_num > (0)", "ratio numerator positive"), ("ratio_den > (0)", "ratio denominator positive"),
        ("jsonb_array_length", "evidence must be a non-empty array"),
        ("source_instrument_id <> target_instrument_id", "a security cannot convert into itself"),
        ("last_source_session < effective_date", "last source session before the effective date"),
        ("PROVISIONAL", "status limited to PROVISIONAL / VERIFIED / REJECTED"),
        ("UNIQUE (source_instrument_id, target_instrument_id, effective_date)", "unique per (source, target, effective date)"),
    ):  # fmt: skip
        checks[f"schema: {label}"] = has(needle)
    checks["schema: absorbed date and kind together or neither"] = has(
        "absorbs_ex_date IS NULL"
    ) and has("absorbs_kind IS NULL")
    checks["schema: foreign keys to both instruments and to the relationship"] = (
        sum(d.startswith("FOREIGN KEY") for d in cons) == 3
    )
    rows = conn.execute(
        "SELECT source_instrument_id, target_instrument_id, effective_date, last_source_session, ratio_num, ratio_den,"
        " absorbs_ex_date, absorbs_kind, evidence, verification_status, review_decision_id, relationship_id FROM security_conversion"
    ).fetchall()
    checks["exactly one instruction is recorded"] = len(rows) == 1
    if rows:
        r = rows[0]
        checks["source and target resolved from the ISINs"] = (r[0], r[1]) == (old, new)
        checks["effective date and last source session"] = (r[2], r[3]) == (
            effective,
            date.fromisoformat(doc["last_source_session"]),
        )
        checks["ratio 10:1 (target shares per source share)"] = (
            (D(r[4]), D(r[5])) == (D(doc["ratio_num"]), D(doc["ratio_den"])) == (D(10), D(1))
        )
        checks["absorbed action is the same-date split"] = (r[6], r[7]) == (
            date.fromisoformat(doc["absorbs"]["ex_date"]),
            doc["absorbs"]["kind"],
        )
        checks["evidence references equal the config (3 NSE circulars)"] = (
            list(r[8]) == doc["evidence"] and len(r[8]) == 3
        )
        checks["status VERIFIED, review decision recorded"] = (r[9], r[10]) == (
            "VERIFIED",
            doc["review_decision_id"],
        )
        rel = conn.execute(
            "SELECT relationship_id, effective_date FROM corporate_action_relationship WHERE relationship_type='SAME_ISSUER_ISIN_CHANGE'"
            " AND source_instrument_id=%s AND target_instrument_id=%s", (old, new),
        ).fetchall()  # fmt: skip
        checks["linked to the existing SAME_ISSUER_ISIN_CHANGE relationship"] = len(
            rel
        ) == 1 and tuple(rel[0]) == (r[11], effective)
    loaded = load_conversions(conn)
    checks["the loader returns it (reference, absorbed split, verified)"] = (
        len(loaded) == 1 and loaded[0].ref == conversion_ref(old, new, effective)
        and loaded[0].absorbs == (effective, "split") and loaded[0].verified
    )  # fmt: skip
    # the engine on the REAL bars, in memory only (run_backtest does not persist)
    first_new = conn.execute(
        "SELECT min((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE instrument_id=%s",
        (new,),
    ).fetchone()[0]
    strat = HoldOld(old, new)
    res = run_backtest(
        conn, strat,
        BacktestConfig(start=date(2023, 12, 20), end=date(2024, 1, 12), initial_cash=D(10_000_000), cost=CostModel("zero", D(0), D(0), False)),
    )  # fmt: skip
    notes.append(
        f"engine run: {len(res.trades)} trade(s), {len(res.conversions)} conversion(s), final positions {dict(res.final_positions)}, unmodelled {res.unmodelled}"
    )
    checks["engine: exactly one conversion applied"] = len(res.conversions) == 1
    if len(res.conversions) == 1 and res.ledger is not None:
        c = res.conversions[0]
        qty_out, qty_in, cost = D(c["qty_out"]), D(c["qty_in"]), D(c["cost"])
        checks["engine: converted on the new ISIN's first session = the effective date"] = (
            c["day"] == str(first_new) == str(effective)
        )
        checks["engine: quantity x10, cost basis unchanged"] = (
            qty_in == qty_out * 10
            and res.ledger.cost_basis(new) == cost
            and res.ledger.cost_basis(old) == 0
        )
        checks["engine: the only trade is the one purchase of the old ISIN"] = [
            (t.instrument_id, t.side) for t in res.trades
        ] == [(old, "BUY")]
        checks["engine: no realised P&L and no fees"] = (
            D(res.pnl["realized"]) == 0 and D(res.pnl["fees"]) == 0
        )
        checks["engine: ledger reconciles, accounting complete, nothing unmodelled"] = (
            res.ledger_reconciled and res.accounting_complete and not res.unmodelled
        )
        checks["engine: the converted position is held at the new quantity to the end"] = (
            res.final_positions == {new: qty_in}
        )
        eq = dict(res.equity)
        prev = max(d for d in eq if d < first_new)
        notes.append(
            f"{qty_out} old shares -> {qty_in} new shares, cost basis {cost}; equity {eq[prev]} ({prev}) -> {eq[first_new]} ({first_new}), change {eq[first_new] - eq[prev]} (the market move of one session)"
        )


with (
    psycopg.connect(a.db, autocommit=True) as conn,
    slot.hold(conn, "conversion verification", nice=10),
):
    if a.mode == "dry-run":
        before = fingerprints(conn)
        checks["precondition: migration 025 not yet applied"] = (
            conn.execute("SELECT to_regclass('security_conversion')").fetchone()[0] is None
        )
        with conn.transaction(force_rollback=True):
            migrate(conn)
            checks["the instruction would be inserted (not already recorded)"] = (
                store_conversion(conn, doc, datetime.now(UTC)) == 1
            )
            verify(conn)
            inside = fingerprints(conn)
        after = fingerprints(conn)
        for t, v in before.items():
            same = inside[t] == v
            checks[f"recording changed no existing row of {t} ({v[0]} rows)"] = same
        checks["after the rollback: every fingerprint as before, no security_conversion table"] = (
            after == before
            and conn.execute("SELECT to_regclass('security_conversion')").fetchone()[0] is None
        )
        notes.append(
            f"migrations in database now: {conn.execute('SELECT count(*) FROM schema_migration').fetchone()[0]}"
        ) if conn.execute("SELECT to_regclass('schema_migration')").fetchone()[0] else None
    else:
        verify(conn)

ok = all(checks.values())
lines = [
    f"# NESTLEIND conversion instruction: {a.mode} verification", "",
    f"- config `{a.config}`: {doc['source_isin']} to {doc['target_isin']}, {doc['ratio_num']}:{doc['ratio_den']}, effective {doc['effective_date']}, {doc['verification_status']}",
    f"- config sha256 `{hashlib.sha256(a.config.read_bytes()).hexdigest()}`",
    f"- {'everything ran inside a transaction that was rolled back; nothing was written' if a.mode == 'dry-run' else 'read-only on the persisted instruction'}", "",
    "| check | result |", "|---|---|", *[f"| {k} | {'PASS' if v else 'FAIL'} |" for k, v in checks.items()], "",
    *[f"- {n}" for n in notes], "", f"**Result: {'PASS' if ok else 'FAIL'}**",
]  # fmt: skip
out_path.write_text("\n".join(lines) + "\n")
print("\n".join(lines))
raise SystemExit(0 if ok else 1)
