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
        f"| {p['item_id']} | {p['decision']} (#{p['decision_id']}) | {p['kind']} | {len(p['actions'])} |"
    )
md += [
    "", "## Reading notes", "",
    "- `listed_on` in a proposed instrument is the FIRST DATE IN OUR EXCHANGE-FILE ARCHIVE, not necessarily the true listing date.",
    "- ISINs are the ones seen in our own exchange files for the symbol; none was checked against NSDL/CDSL.",
    "- End dates are exclusive: `valid_to` / `delisted_on` is the first day the security no longer trades (last session + 1).",
    "- 'successor' and 'continuity' records have NO table yet: they are corporate-action facts, never aliases. A schema decision is needed before they can be applied.",
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
        md += [f"- CAVEAT: {cv}" for cv in p["caveats"]] + [""]
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
