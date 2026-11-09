# ruff: noqa: E501  (a proposal report script)
"""PROPOSAL-ONLY: turn the recorded review decisions into the exact writes a person would approve, and
dry-run which membership exceptions they would clear. Read-only database session; nothing is written to the
instrument master, aliases, membership or coverage tables, and the adopted membership baseline is untouched.
usage: propose_review_application.py --db postgresql://... [--out docs/stage4/apply_proposals]"""

import argparse
import csv
import json
import os
from datetime import date
from pathlib import Path

import psycopg

from algo.data.apply_proposals import dry_run, membership_proposal, parse_facts, symbol_proposal

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out", type=Path, default=Path("docs/stage4/apply_proposals"))
ap.add_argument("--anchor", default="2026-11-07")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")

REFLECTED = {
    "CENTRALBK": ["config/revocations/pr_ind_prs25092024.json"],
    "IDEA": ["config/revocations/pr_ind_prs25092024.json"],
    "IREDA": ["config/revocations/pr_ind_prs19032024.json"],
    "TATAMTRDVR": ["parser v7: 'excluded from the following indices' notices (nse_index_releases.py)"],
    "DUMMYABFRL": ["config/placeholder_replacements/pr_ind_prs25062025_2.json"],
    "DUMMYSIEMS": ["config/placeholder_replacements/pr_ind_prs25062025_2.json"],
    "ITCHOTELS": ["config/placeholder_replacements/pr_ind_prs06022025_1.json"],
    "JIOFIN": ["config/transcriptions/pr_ind_prs17072023.json", "config/placeholder_replacements/pr_ind_prs05092023.json", "config/entity_equivalence/dummyrel.json"],
    "NESTLEIND": ["config/entity_equivalence/nestleind.json"],
    "BSE": ["config/transcriptions/pr_ind_prs19032024.json"],
}  # fmt: skip
base = Path("docs/stage4/membership")
exceptions = list(csv.DictReader((base / "membership_exceptions.csv").open()))
intervals = list(csv.DictReader((base / "membership_intervals.csv").open()))
open_symbols = {e["symbol"] for e in exceptions if e["kind"].startswith(("WALK_", "SNAPSHOT_"))}
items = json.loads(Path("docs/stage4/review/review_items.json").read_text())["items"]

DATE_COLUMN = {
    "bar_1d": "ts::date",
    "corporate_action": "ex_date",
    "index_release_row": "effective_from",
}
TABLES = [
    "action_resolution", "backtest_ledger", "backtest_trade", "bar_1d", "corporate_action",
    "index_membership_event", "index_monthly_constituent", "index_release_row", "index_snapshot",
    "instrument_alias", "instrument_terms",
]  # fmt: skip


def dependents(c, iid, change):
    """Per table: (rows referencing the instrument, rows dated before `change`; 0 without a date column)."""
    out = {}
    for t in TABLES:
        col = DATE_COLUMN.get(t)
        before = f"count(*) FILTER (WHERE {col} < %s)" if col else "0"
        params = (change, iid) if col else (iid,)
        latest = " AND parser_version = (SELECT max(parser_version) FROM index_release_document)"
        extra = latest + " AND component IS NOT NULL" if t == "index_release_row" else ""
        out[t] = tuple(
            c.execute(
                f"SELECT count(*), {before} FROM {t} WHERE instrument_id = %s{extra}", params
            ).fetchone()
        )
    out["unmapped_release_rows"] = tuple(
        c.execute(
            "SELECT count(*), count(*) FROM index_release_row WHERE symbol = (SELECT symbol FROM instrument WHERE instrument_id=%s)"
            " AND instrument_id IS NULL AND component IS NOT NULL"
            " AND parser_version = (SELECT max(parser_version) FROM index_release_document)",
            (iid,),
        ).fetchone()
    )
    check = Path("docs/stage4/apply_proposals/nestleind_reader_check.md")
    out["reader_check"] = (
        "PASS" if check.exists() and "**Result: PASS**" in check.read_text() else "NOT RUN"
    )
    return out


proposals = []
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    latest = {
        r[0]: {"decision_id": r[1], "decision": r[2], "effective_date": r[3], "reviewer": r[4], "evidence_ref": r[5]}
        for r in c.execute(
            "SELECT DISTINCT ON (item_id) item_id, decision_id, decision, effective_date, reviewer, evidence_ref"
            " FROM review_decision ORDER BY item_id, decision_id DESC"
        ).fetchall()
    }  # fmt: skip
    for item in items:
        rec = latest[item["id"]]
        if item["kind"] == "SYMBOL_IDENTITY":
            sym = item["id"].split(":", 1)[1]
            row = c.execute(
                "SELECT instrument_id, isin FROM instrument WHERE symbol=%s ORDER BY instrument_id LIMIT 1",
                (sym,),
            ).fetchone()
            al = (
                c.execute("SELECT valid_from, valid_to FROM instrument_alias WHERE instrument_id=%s AND source='nse' AND source_symbol=%s", (row[0], sym)).fetchall()
                if row else []
            )  # fmt: skip
            existing = {
                "instrument": {"id": row[0], "isin": row[1]} if row else None,
                "aliases": [tuple(x) for x in al],
            }
            if row and rec["decision"] == "SET_EFFECTIVE_DATE":
                existing["dependents"] = dependents(c, row[0], rec["effective_date"])
            proposals.append(symbol_proposal(sym, rec, parse_facts(item["context"]), existing))
        else:
            sym = item["title"].split(":", 1)[0]
            proposals.append(
                membership_proposal(item["id"], rec, REFLECTED[sym], sym in open_symbols)
            )

result = dry_run(exceptions, intervals, proposals, date.fromisoformat(a.anchor))
a.out.mkdir(parents=True, exist_ok=True)
(a.out / "proposals.json").write_text(
    json.dumps(
        {
            "status": "PROPOSED_NOT_APPLIED",
            "count": len(proposals),
            "proposals": proposals,
            "dry_run": result,
        },
        indent=1,
        default=str,
    )
    + "\n"
)
md = ["# Apply proposals (PROPOSAL ONLY, nothing applied)", "",
      f"{len(proposals)} recorded review decisions -> proposals. No write was made to the instrument master, aliases, membership or coverage tables.", "",
      "| item | decision | kind | writes |", "|---|---|---|---|"]  # fmt: skip
for p in proposals:
    md.append(
        f"| {p['item_id']} | {p['decision']} (#{p['decision_id']}) | {p['kind']}{' [BLOCKED]' if p['status'] == 'BLOCKED' else ''} | {len(p['actions'])} |"
    )
md += [
    "", "## Reading notes", "",
    "- `listed_on` is proposed as NULL everywhere: a listing date is a verified fact. The first and last date in our archive are stored separately as `first_observed_on` / `last_traded_on`.",
    "- Alias `valid_from` / `valid_to` carry a basis (`FIRST_OBSERVED`, `LAST_OBSERVED`, `EVIDENCED`): an archive boundary is a floor for resolution, never a claim about when a symbol began or ended. `delisted_on` is set only where a primary document states it (MINDTREE, HEXAWARE).",
    "- ISINs are the ones seen in our own exchange files for the symbol; none was checked against NSDL/CDSL.",
    "- End dates are exclusive: `valid_to` / `delisted_on` is the first day the security no longer trades (last session + 1).",
    "- Successors and relistings are `corporate_action_relationship` rows (migration 024): typed, effective-dated, with an optional ratio, `known_at` (empty: no announcement date is recorded yet) and evidence. They are never aliases.",
    "- NESTLEIND is BLOCKED: see its section for the dependent rows and the plan that needs your approval first.",
    "- MINDTREE and HEXAWARE were recorded with the 'no successor' option only to capture the last day; the successor facts above come from the decision notes.",
    "- Applying any of this changes which membership exceptions clear only as shown in dry_run.md; it does not by itself make the Nifty 200 point-in-time universe ready.",
]  # fmt: skip
md += ["", "## Writes proposed per item", ""]
for p in proposals:
    if p["actions"] or p["caveats"]:
        md += [f"### {p['item_id']} ({p['kind']})", p["summary"], ""]
        md += [
            f"- {x['operation']} {x['table']}: `{json.dumps(x['values'], default=str)}`"
            for x in p["actions"]
        ]
        label = "BLOCKER" if p["status"] == "BLOCKED" else "CAVEAT"
        md += [f"- {label}: {cv}" for cv in p["caveats"]]
        md += [f"- PLAN IF APPROVED ({n}): {x}" for n, x in enumerate(p["plan_if_approved"], 1)]
        md.append("")
(a.out / "proposals.md").write_text("\n".join(md) + "\n")
dr = [
    "# Dry run: instrument-resolution exceptions",
    "",
    "| entity | result | reason |",
    "|---|---|---|",
]
dr += [f"| {r['entity']} | {r['result']} | {r['reason']} |" for r in result]
(a.out / "dry_run.md").write_text("\n".join(dr) + "\n")
print(
    f"{len(proposals)} proposals; dry run: "
    + "; ".join(f"{r['entity']} {r['result']}" for r in result)
)
