# ruff: noqa: E501
"""Build the evidence record for the owner-approved verification of provisional corporate actions, recompute every factor, and (only with --apply)
mark them verified. The default is READ-ONLY: it writes the evidence record and factor calculations for review and changes nothing in the database.
usage: verify_provisional_actions.py --db postgresql://... [--decision config/corporate_action_verification/2026-11-15.json] [--apply --by NAME]"""

import argparse
import csv
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from algo.data.adjust.factors import rights_factor
from algo.data.review import ResolveError, verify

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--decision", type=Path, default=Path("config/corporate_action_verification/2026-11-15.json")
)
ap.add_argument("--out", type=Path, default=Path("docs/stage4/corporate_actions"))
ap.add_argument(
    "--kite-csv",
    type=Path,
    default=Path("docs/stage4/corporate_actions/provisional_cross_check_2026-11-15.csv"),
)
ap.add_argument("--apply", action="store_true")
ap.add_argument("--by")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
if a.apply and not a.by:
    raise SystemExit("error: --apply needs --by (who verifies)")
dec = json.loads(a.decision.read_text())
kite = {(r["symbol"], r["ex_date"]): r for r in csv.DictReader(a.kite_csv.open())}
records, calcs, problems = [], [], []
with psycopg.connect(a.db) as conn:
    for it in dec["approved"]:
        d = date.fromisoformat(it["ex_date"])
        row = conn.execute(
            "SELECT r.id, r.factor, r.method, r.inputs, r.note, r.status, r.source_type, r.source_url FROM action_resolution r JOIN instrument i USING (instrument_id)"
            " WHERE i.symbol=%s AND r.ex_date=%s AND r.kind=%s ORDER BY r.id DESC LIMIT 1", (it["symbol"], d, it["kind"]),
        ).fetchone()  # fmt: skip
        if row is None or row[5] != "provisional":
            problems.append(
                f"{it['symbol']} {d}: latest resolution is {row[5] if row else 'missing'}, not provisional"
            )
            continue
        rid, factor, method, inputs, _, _, stype, surl = row
        ev = inputs.get("evidence", {})
        if method == "exchange_adjusted_price":
            base, prev = Decimal(inputs["base_price"]), Decimal(inputs["prev_close"])
            recomputed, calc = (
                base / prev,
                {
                    "base_price": str(base),
                    "prev_close": str(prev),
                    "formula": "base_price / prev_close",
                },
            )
            url, kind = (ev.get("reports") or [{}])[0].get("url"), "press_report"
        elif method == "rights":
            n, h, s = (
                Decimal(inputs["new"]),
                Decimal(inputs["held"]),
                Decimal(inputs["subscription_price"]),
            )
            prev = (
                Decimal(ev["prev_close_cum"])
                if "prev_close_cum" in ev
                else Decimal(inputs["prev_close"])
            )
            recomputed, calc = (
                rights_factor(n, h, s, prev),
                {
                    "new": str(n),
                    "held": str(h),
                    "subscription_price": str(s),
                    "prev_close": str(prev),
                    "formula": "TERP / prev_close",
                },
            )
            url, kind = (
                (ev.get("issuer_document") or {}).get("url") or surl,
                "issuer_document"
                if "issuer_document" in ev or not surl
                else (stype or "press_report"),
            )
        else:
            problems.append(f"{it['symbol']} {d}: method {method} is not verifiable here")
            continue
        if not url:
            problems.append(f"{it['symbol']} {d}: no source url on record")
            continue
        diff = abs(recomputed - factor)
        if diff > Decimal("1e-9"):
            problems.append(
                f"{it['symbol']} {d}: recomputed factor {recomputed} differs from stored {factor}"
            )
        k = kite.get((it["symbol"], it["ex_date"]), {})
        rec = {**it, "resolution_id": rid, "method": method, "stored_factor": str(factor), "recomputed_factor": str(recomputed), "calculation": calc, "source_type": kind, "source_url": url,
               "evidence_on_record": ev, "kite_implied_factor": k.get("kite_implied_factor"), "kite_over_stored": k.get("kite_over_stored")}  # fmt: skip
        records.append(rec)
        calcs.append(
            [
                it["symbol"],
                it["ex_date"],
                it["kind"],
                it["group"],
                it["provenance"],
                method,
                *[
                    calc.get(c, "")
                    for c in ("prev_close", "base_price", "new", "held", "subscription_price")
                ],
                str(factor),
                str(recomputed),
                str(diff),
                k.get("kite_implied_factor", ""),
            ]
        )
    out = {
        "decision": dec,
        "generated": datetime.now(UTC).isoformat(),
        "records": records,
        "problems": problems,
    }
    (a.out / "verification_evidence_2026-11-15.json").write_text(
        json.dumps(out, indent=1, default=str)
    )
    with (a.out / "verification_factor_calculations_2026-11-15.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "symbol",
                "ex_date",
                "kind",
                "group",
                "provenance",
                "method",
                "prev_close",
                "base_price",
                "rights_new",
                "rights_held",
                "rights_subscription_price",
                "stored_factor",
                "recomputed_factor",
                "abs_difference",
                "kite_implied_factor",
            ]
        )
        w.writerows(calcs)
    print(f"evidence records {len(records)} of {len(dec['approved'])}; problems {len(problems)}")
    for p in problems:
        print("PROBLEM", p)
    if a.apply:
        if problems:
            raise SystemExit("refusing to apply while there are problems")
        now = datetime.now(UTC)
        for rec in records:
            try:
                verify(conn, symbol=rec["symbol"], ex_date=date.fromisoformat(rec["ex_date"]), kind=rec["kind"], by=a.by, now=now, source_type=rec["source_type"], source_url=rec["source_url"],
                       note=f"verified {now.date()} by {a.by}: {rec['provenance']} ({dec['provenance_labels'][rec['provenance']]}); owner decision {dec['decided']}, record {a.decision}",
                       evidence={"provenance": rec["provenance"], "group": rec["group"], "owner_decision": dec["decided"], "decision_record": str(a.decision), "kite_implied_factor": rec["kite_implied_factor"], "methodology": dec["methodology"]["demerger"] if rec["kind"] == "demerger" else "rights: TERP from issuer terms"})  # fmt: skip
            except ResolveError as e:
                conn.rollback()
                raise SystemExit(f"stopped, nothing applied: {e}") from e
        conn.commit()
        print(f"verified {len(records)} actions in {a.by}'s name")
    else:
        conn.rollback()
        print(
            "read-only: evidence record and factor calculations written; nothing changed in the database"
        )
