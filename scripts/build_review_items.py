# ruff: noqa: E501  (item prose; this is a script, not library code)
"""Builds the review queue the console shows: docs/stage4/review/review_items.json.

Items are the open questions from the symbol classification (Nifty-family symbols only) and the
membership reconstruction exceptions. Each carries the evidence, where to look, and the options a
person may choose from. Deterministic; read-only on its inputs."""

import csv
import json
import re
from pathlib import Path

SYM = Path("docs/stage4/symbol_classification/symbol_classification.csv")
EXC = Path("docs/stage4/membership/membership_exceptions.csv")
OUT = Path("docs/stage4/review/review_items.json")

SYMBOL_OPTIONS = [
    {
        "value": "CONFIRM_MAPPING",
        "label": "Same security: map to the candidate",
        "needs_date": True,
        "date_label": "Alias valid from",
    },
    {
        "value": "KEEP_SEPARATE",
        "label": "Different security: keep as its own identity",
        "needs_date": False,
    },
    {
        "value": "SET_EFFECTIVE_DATE",
        "label": "Source confirms the effective date",
        "needs_date": True,
        "date_label": "Effective date",
    },
    {
        "value": "NO_SUCCESSOR",
        "label": "Ceased: no successor (delisted / merged away)",
        "needs_date": True,
        "date_label": "Last day as a listed security",
    },
    {"value": "KEEP_PLACEHOLDER", "label": "Non-tradable placeholder", "needs_date": False},
    {
        "value": "NEEDS_MORE_EVIDENCE",
        "label": "Not decided: need more evidence",
        "needs_date": False,
        "needs_evidence": False,
    },
]
MEMBERSHIP_OPTIONS = [
    {
        "value": "RECONSTRUCTION_CORRECT",
        "label": "Reconstruction is right (the snapshot is wrong or incomplete)",
        "needs_date": False,
    },
    {
        "value": "CORRECT_DATE",
        "label": "Real effective date differs",
        "needs_date": True,
        "date_label": "Correct effective date",
    },
    {
        "value": "NOT_A_MEMBER",
        "label": "Not a member during this span",
        "needs_date": True,
        "date_label": "Not a member from",
        "has_end": True,
    },
    {
        "value": "PARSER_ERROR",
        "label": "The release was misread by the parser",
        "needs_date": False,
    },
    {
        "value": "NEEDS_MORE_EVIDENCE",
        "label": "Not decided: need more evidence",
        "needs_date": False,
        "needs_evidence": False,
    },
]


def leads(text: str) -> list[str]:
    return sorted(set(re.findall(r"pr_ind_prs\d+(?:_\d+)?", text)))


items: list[dict] = []
for r in csv.DictReader(SYM.open()):
    if r["scope"] != "NIFTY200_FAMILY":
        continue
    items.append(
        {
            "id": f"symbol:{r['symbol']}",
            "kind": "SYMBOL_IDENTITY",
            "title": f"{r['symbol']}: {r['release_companies'] or 'no company name'}",
            "question": "What is this symbol's identity, and from when?",
            "category": r["category"],
            "confidence": r["confidence"],
            "context": {
                k: v
                for k, v in {
                    "Proposed category": f"{r['category']} ({r['confidence']})",
                    "Release rows": f"{r['family_rows']} Nifty-family rows, first effective {r['first_release_effective'] or 'NONE'}, last {r['last_release_effective'] or 'NONE'}",
                    "Exchange files": f"{r['first_exchange_file'] or '-'} .. {r['last_exchange_file'] or '-'} ({r['sessions_legacy']} legacy / {r['sessions_modern']} modern sessions)",
                    "ISINs seen": r["isins_in_exchange_files"],
                    "Candidate": f"{r['candidate_symbol']} {r['candidate_isin']} ({r['candidate_status']}, {r['candidate_bars']} bars {r['candidate_bar_range']})"
                    if r["candidate_symbol"]
                    else "",
                    "Why proposed": r["relation_evidence"],
                    "Notes": r["notes"],
                    "Prices recoverable from": r["prices_recoverable_from"],
                }.items()
                if v
            },
            "leads": leads(r["notes"] + r["relation_evidence"]),
            "options": SYMBOL_OPTIONS,
        }
    )
seen: set[str] = set()
for r in csv.DictReader(EXC.open()):
    if r["kind"] in ("PLACEHOLDER_NOT_TRADABLE", "MEMBER_WITHOUT_INSTRUMENT"):
        continue  # covered by the symbol items
    key = f"membership:{r['kind']}:{r['symbol']}:{r['component']}:{r['effective']}"
    if key in seen:
        continue
    seen.add(key)
    detail = r["detail"]
    items.append(
        {
            "id": key,
            "kind": "MEMBERSHIP_EXCEPTION",
            "title": f"{r['symbol']}: {r['kind'].replace('_', ' ').lower()}",
            "question": "Which is right: the reconstruction or the independent snapshot?"
            if r["kind"] == "SNAPSHOT_MISMATCH_BLOCK"
            else "Is this release transition correct?",
            "category": r["kind"],
            "confidence": "",
            "context": {
                k: v
                for k, v in {
                    "Entity": r["entity"],
                    "Component": r["component"],
                    "Effective": r["effective"],
                    "Blocked span": r["blocked"],
                    "Detail": detail,
                }.items()
                if v
            },
            "leads": leads(detail),
            "options": MEMBERSHIP_OPTIONS,
        }
    )
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(
    json.dumps({"generated_from": [str(SYM), str(EXC)], "items": items}, indent=1, sort_keys=True)
    + "\n"
)
print(
    len(items),
    "items;",
    sum(1 for i in items if i["kind"] == "SYMBOL_IDENTITY"),
    "symbol,",
    sum(1 for i in items if i["kind"] != "SYMBOL_IDENTITY"),
    "membership",
)
