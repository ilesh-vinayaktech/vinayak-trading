# ruff: noqa: E501  (a report script)
"""Record reviewed corporate-action resolutions from a config file. DRY RUN BY DEFAULT: everything runs
inside one transaction that is always rolled back; --apply commits. Append-only (resolve() inserts a new row;
earlier rows stay as audit history).

Before each insert, from the STORED exchange file: its SHA-256 equals the config, and its row for the symbol has
OPEN_PRICE = base price and PREV_CLOSE = the expected previous close; the database's previous close agrees.
After each insert: it is the latest resolution, factor = base / prev close at full precision, evidence class
PROVISIONAL_EXCHANGE_DERIVED, the earlier estimate is kept but superseded, strict reads still treat the action as
unresolved (provisional is not verified) and research reads apply the new factor.
usage: record_action_resolutions.py --db URL --config config/action_resolutions/<file>.json [--apply]
       [--out docs/stage4/corporate_actions/<config-stem>_<dry_run|applied>.md]"""

import argparse
import csv
import hashlib
import io
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from algo.data.corporate_actions import records_for
from algo.data.review import evidence_class, resolve

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--config", type=Path, required=True)
ap.add_argument("--apply", action="store_true")
ap.add_argument("--by", default="claude-research (owner-approved provisional recording)")
ap.add_argument("--out", type=Path, default=None)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
cfg = json.loads(a.config.read_text())
mode = "applied" if a.apply else "dry_run"
out = a.out or Path(f"docs/stage4/corporate_actions/{a.config.stem}_{mode}.md")
checks: list[tuple[str, str, bool, str]] = []  # (symbol, check, ok, detail)
D = Decimal


def check(sym: str, name: str, ok: bool, detail: str = "") -> None:
    checks.append((sym, name, bool(ok), detail))


def file_row(path: Path, symbol: str) -> dict[str, str] | None:
    rows = list(csv.reader(io.StringIO(path.read_bytes().decode())))
    head = [h.strip() for h in rows[0]]
    for r in rows[1:]:
        d = dict(zip(head, (x.strip() for x in r), strict=False))
        if d.get("SYMBOL") == symbol and d.get("SERIES") == "EQ":
            return d
    return None


def latest(conn, iid: int, ex: date, kind: str):
    return conn.execute(
        "SELECT id, method, status, factor, inputs, source_url FROM action_resolution WHERE instrument_id=%s AND ex_date=%s AND kind=%s ORDER BY id DESC",
        (iid, ex, kind),
    ).fetchall()


def run(conn: psycopg.Connection) -> None:
    now = datetime.now(UTC)
    for it in cfg["resolutions"]:
        sym, ex, kind = it["symbol"], date.fromisoformat(it["ex_date"]), it["kind"]
        base, prev = D(it["base_price"]), D(it["expected_prev_close"])
        bh = it["bhavcopy"]
        f = Path(bh["path"])
        sha = hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else ""
        check(sym, "stored bhavcopy SHA-256 equals the config", sha == bh["sha256"], sha[:16])
        row = file_row(f, bh["symbol_in_file"]) if f.exists() else None
        check(sym, "bhavcopy row: OPEN_PRICE = base price, PREV_CLOSE = expected previous close",
              row is not None and D(row["OPEN_PRICE"]) == base and D(row["PREV_CLOSE"]) == prev,
              f"{bh['symbol_in_file']} {row['DATE1'] if row else 'missing'} open {row['OPEN_PRICE'] if row else '-'} prev {row['PREV_CLOSE'] if row else '-'}")  # fmt: skip
        iid = conn.execute(
            "SELECT instrument_id FROM instrument WHERE symbol=%s", (sym,)
        ).fetchone()[0]  # type: ignore[index]
        db_prev = conn.execute(
            "SELECT close FROM bar_1d WHERE instrument_id=%s AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY ts DESC LIMIT 1",
            (iid, ex),
        ).fetchone()[0]  # type: ignore[index]
        check(
            sym,
            "database previous close equals the exchange file",
            D(db_prev) == prev,
            str(db_prev),
        )
        before = latest(conn, iid, ex, kind)
        evidence = {
            "formula": cfg["formula"], "calculation_version": cfg["calculation_version"],
            "ex_date_open": str(base), "prev_close_cum": str(prev), "entitlement_reported": it["entitlement_reported"],
            "bhavcopy": bh, "reports": it["reports"], "limitation": it["limitation"],
            "supersedes_resolution_id": before[0][0] if before else None,
            "superseded_method": before[0][1] if before else None,
        }  # fmt: skip
        r = resolve(conn, symbol=sym, ex_date=ex, kind=kind, method=cfg["method"], params={"base_price": base},
                    note=f"exchange-derived provisional: {it['limitation']}", by=a.by, now=now,
                    status=cfg["status"], evidence=evidence)  # fmt: skip
        after = latest(conn, iid, ex, kind)
        new = after[0]
        check(
            sym,
            "a new row was appended and is now the latest",
            len(after) == len(before) + 1 and new[1] == cfg["method"],
            f"id {new[0]}",
        )
        check(
            sym,
            "factor = base / previous close at full precision",
            new[3] == base / prev == r.factor,
            str(new[3]),
        )
        check(
            sym,
            "status provisional, no official source claimed",
            new[2] == "provisional" and new[5] is None,
        )
        check(
            sym,
            "evidence class PROVISIONAL_EXCHANGE_DERIVED",
            evidence_class(new[2], new[1]) == "PROVISIONAL_EXCHANGE_DERIVED",
        )
        check(sym, "evidence stored with the calculation inputs kept apart",
              new[4]["base_price"] == str(base) and new[4]["prev_close"] == str(prev) and new[4]["evidence"]["bhavcopy"]["sha256"] == bh["sha256"])  # fmt: skip
        check(sym, "the earlier estimate is kept as history, superseded",
              not before or (after[1][0] == before[0][0] and after[1][1] == before[0][1]),
              f"earlier: {before[0][1]} {D(before[0][3]):.6f}" if before else "none")  # fmt: skip
        strict = [x for x in records_for(conn, iid, strict=True) if x.ex_date == ex]
        research = [x for x in records_for(conn, iid) if x.ex_date == ex and x.kind == "resolved"]
        check(
            sym,
            "strict: still unresolved (provisional is not verified)",
            any(x.kind == kind and x.status == "review" for x in strict),
        )
        check(
            sym,
            "research: applies the new factor, flagged provisional",
            len(research) == 1 and research[0].den == new[3] and research[0].provisional,
        )
        if r.warning:
            checks.append((sym, "note from resolve()", True, r.warning))


def count(conn: psycopg.Connection):
    return conn.execute("SELECT count(*), coalesce(max(id),0) FROM action_resolution").fetchone()


with psycopg.connect(a.db, autocommit=True) as conn:
    before_all = count(conn)
    with conn.transaction(force_rollback=not a.apply):
        run(conn)
    after_all = count(conn)
    if a.apply:
        check(
            "ALL",
            "rows appended",
            after_all[0] == before_all[0] + len(cfg["resolutions"]),
            f"{before_all} -> {after_all}",
        )
    else:
        check(
            "ALL",
            "dry run: action_resolution unchanged after the rollback",
            after_all == before_all,
            f"{before_all} -> {after_all}",
        )

ok = all(c[2] for c in checks)
lines = [f"# {a.config.name}: {'APPLY' if a.apply else 'DRY RUN (rolled back; nothing written)'}", "",
         f"- config sha256 `{hashlib.sha256(a.config.read_bytes()).hexdigest()}`; method {cfg['method']}, status {cfg['status']}, {cfg['calculation_version']}",
         f"- formula: {cfg['formula']}", "",
         "| symbol | check | result | detail |", "|---|---|---|---|",
         *[f"| {s} | {n} | {'PASS' if k else 'FAIL'} | {d} |" for s, n, k, d in checks], "", f"**Result: {'PASS' if ok else 'FAIL'}**"]  # fmt: skip
out.write_text("\n".join(lines) + "\n")
print("\n".join(lines))
raise SystemExit(0 if ok else 1)
