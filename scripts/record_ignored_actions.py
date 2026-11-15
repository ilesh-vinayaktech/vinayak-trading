# ruff: noqa: E501
"""Record corporate actions that need NO price adjustment as `ignored_with_reason`, from a config file of reviewed items. DRY RUN unless --apply: all of it
runs in one transaction that is rolled back. Append-only (a new resolution row; earlier rows stay). Each item states its reason and its evidence, which are
stored with the resolution. This is not a verification: it needs no person's attestation, only a documented reason; reopen it if the reason stops holding.
usage: record_ignored_actions.py --db URL --config config/action_resolutions/<file>.json [--apply]"""

import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.review import resolve

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--config", type=Path, required=True)
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
cfg = json.loads(a.config.read_text())
now = datetime.now(UTC)
with psycopg.connect(a.db) as conn:
    with conn.transaction(force_rollback=not a.apply):
        for it in cfg["items"]:
            resolve(conn, symbol=it["symbol"], ex_date=date.fromisoformat(it["ex_date"]), kind=it["kind"], method="ignore", status="ignored_with_reason",
                    note=it["reason"], by=cfg["by"], now=now, evidence={"checked": cfg["checked"], **it.get("evidence", {})})  # fmt: skip
            print(f"{it['symbol']} {it['kind']} ex {it['ex_date']}: ignored with reason")
        n = conn.execute(
            "SELECT count(*) FROM action_resolution WHERE status='ignored_with_reason' AND note LIKE %s",
            (cfg["note_marker"] + "%",),
        ).fetchone()[0]  # type: ignore[index]
        print(f"{n} resolutions carry this config's marker inside the transaction")
print("APPLIED" if a.apply else "dry run: rolled back (pass --apply)")
