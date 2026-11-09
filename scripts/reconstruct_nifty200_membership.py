# ruff: noqa: E501  (report prose; this is a script, not library code)
"""READ-ONLY reconstruction of Nifty 200 membership backward from the verified current snapshots.

Derived Nifty 200 = Nifty 50 + Nifty Next 50 + Nifty Midcap 100 (the 2018-04-02 definition change is
outside the research window). The explicit Nifty 200 sections, the explicit Nifty 100 sections and the
monthly constituent PDFs are INDEPENDENT checkpoints, never used to fill gaps. Nothing is written to
the database and no identity is mapped: unmapped symbols stay separate entities, placeholders stay
non-tradable, and where the evidence disagrees only the affected entity and span are blocked.

usage: reconstruct_nifty200_membership.py --db postgresql://... [--start 2020-10-01] [--out docs/stage4/membership]"""

import argparse
import csv
import glob
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import psycopg

from algo.data.conversions import load_conversions
from algo.data.issuer_series import Link, latest_of
from algo.data.membership_reconstruction import (
    Replacement,
    Revocation,
    Transition,
    apply_replacements,
    apply_revocations,
    block_windows,
    closing_entity,
    combine_rows,
    entity_of,
    equivalence_map,
    hand_over_isin_changes,
    hand_over_spans,
    intervals_from,
    reconcile,
    state_on,
    unify_entities,
    union_events,
    walk_back,
)
from algo.data.providers.nse_index_releases import PARSER_VERSION

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--start", default="2020-10-01")
ap.add_argument("--out", type=Path, default=Path("docs/stage4/membership"))
a = ap.parse_args()
START = date.fromisoformat(a.start)
SCRIPT_VERSION = "membership-reconstruction-1"
COMP = {
    "NIFTY_50": "N50",
    "NIFTY_NEXT_50": "NEXT50",
    "MIDCAP_100": "MID100",
    "NIFTY_100": "N100x",
    "NIFTY_200": "N200x",
}
DERIVED = ["N50", "NEXT50", "MID100"]

with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    inst = {
        r[0]: {
            "symbol": r[1],
            "name": r[2],
            "isin": r[3],
            "delisted_on": r[4],
            "status": r[5],
            "listed_on": r[6],
        }
        for r in c.execute(
            "SELECT instrument_id, symbol, name, isin, delisted_on, status, listed_on FROM instrument"
        )
    }
    anchor_date = c.execute(
        "SELECT max(as_of) FROM index_snapshot WHERE index_id='NIFTY200'"
    ).fetchone()[0]  # type: ignore[index]

    def current(idx: str) -> frozenset[str]:
        return frozenset(
            f"i:{r[0]}"
            for r in c.execute(
                "SELECT instrument_id FROM index_snapshot WHERE index_id=%s AND as_of=%s",
                (idx, anchor_date),
            )
        )

    n50, nx50, mid, n200 = (
        current("NIFTY50"),
        current("NIFTYNEXT50"),
        current("NIFTYMIDCAP100"),
        current("NIFTY200"),
    )
    rows = c.execute(
        """SELECT r.component, r.instrument_id, r.symbol, r.mapping_status, r.action, r.effective_from, d.announced,
                  r.doc_id, r.section_name, d.source_hash, r.parser_version, r.page, d.source_url, r.company,
                  r.related_symbol
           FROM index_release_row r JOIN index_release_document d USING (doc_id, parser_version)
           WHERE r.component = ANY(%s)
             AND r.parser_version = (SELECT max(parser_version) FROM index_release_document x WHERE x.doc_id = r.doc_id)
           ORDER BY d.announced, r.doc_id, r.page, r.section_no, r.symbol""",
        (list(COMP),),
    ).fetchall()
    manual = c.execute(
        "SELECT doc_id, announced, extracted_text FROM index_release_document d WHERE classification='MANUAL_REVIEW_REQUIRED' AND extracted_text IS NOT NULL AND parser_version = (SELECT max(parser_version) FROM index_release_document x WHERE x.doc_id = d.doc_id) ORDER BY announced"
    ).fetchall()
    snaprows = c.execute(
        """SELECT s.component, s.as_of, s.pdf_name, s.pdf_hash, s.parser_version, k.instrument_id, k.symbol, k.mapping_status
           FROM index_monthly_snapshot s JOIN index_monthly_constituent k USING (snapshot_id)
           WHERE s.component = ANY(%s) AND s.parser_version = (SELECT max(parser_version) FROM index_monthly_snapshot y WHERE y.index_name = s.index_name AND y.as_of = s.as_of)""",
        (list(COMP),),
    ).fetchall()
    revrows = c.execute(
        """SELECT v.doc_id, v.authority_doc, v.component, v.symbol,
                  CASE v.kind WHEN 'INCLUSION_REVOKED' THEN 'INCLUDED' ELSE 'EXCLUDED' END,
                  v.effective_from, v.authority_date, d.source_hash
           FROM index_release_revocation v
           LEFT JOIN index_release_document d ON d.doc_id = v.authority_doc AND d.parser_version = %s
           WHERE v.component = ANY(%s) ORDER BY v.authority_date, v.symbol""",
        (PARSER_VERSION, list(COMP)),
    ).fetchall()
    has_rel = c.execute("SELECT to_regclass('corporate_action_relationship')").fetchone()[0]
    isin_links = (
        [
            Link(*r)
            for r in c.execute(
                "SELECT source_instrument_id, target_instrument_id, effective_date"
                " FROM corporate_action_relationship"
                " WHERE relationship_type='SAME_ISSUER_ISIN_CHANGE' AND target_instrument_id IS NOT NULL"
            ).fetchall()
        ]
        if has_rel
        else []
    )
    reprows = c.execute(
        "SELECT placeholder, symbol, listed_on, evidence_doc FROM index_placeholder_replacement"
        " ORDER BY listed_on, symbol"
    ).fetchall()
    handover = [(v.source, v.target, v.effective) for v in load_conversions(c)]  # VERIFIED only

replaced = frozenset(r[0] for r in reprows)
same_issuer = {f"i:{a}": f"i:{b}" for a, b in latest_of(isin_links).items()}  # comparison only
trs = [
    Transition(
        COMP[comp],
        closing_entity(iid, sym, ms, rel, act, replaced),
        sym,
        act,
        eff,
        ann,
        doc,
        sec,
        h,
        pv,
        pg,
    )
    for comp, iid, sym, ms, act, eff, ann, doc, sec, h, pv, pg, _, _co, rel in rows
]
revocations = [Revocation(r[0], r[1], COMP[r[2]], r[3], r[4], r[5]) for r in revrows]
trs, cancelled, unmatched_revocations = apply_revocations(trs, revocations)
listing_entity = {r[2]: entity_of(r[1], r[2], r[3]) for r in rows}  # stock symbol -> its entity
replacements = [
    Replacement(
        ph,
        listing_entity.get(sym, f"s:{sym}"),
        sym,
        listed,
        doc,
        None if ph.startswith("DUMMY") else f"s:{ph}",  # a pre-alias entity keeps its symbol key
    )
    for ph, sym, listed, doc in reprows
]
trs, unmatched_replacements = apply_replacements(trs, replacements)
equiv_records = [
    json.loads(f.read_text()) for f in sorted(Path("config/entity_equivalence").glob("*.json"))
]
equivalent = equivalence_map(equiv_records)
trs = unify_entities(trs, equivalent)
doc_url = {r[7]: r[12] for r in rows}
company_of: dict[str, str] = {}
for r in rows:
    company_of.setdefault(entity_of(r[1], r[2], r[3]), r[13])


def manual_leads(e: str) -> str:
    """Unparsed press releases whose text mentions the entity: where a person should look. A lead, not evidence."""
    sym = e[2:] if not e.startswith("i:") else inst[int(e[2:])]["symbol"]
    names = (
        [sym]
        + ([company_of[e]] if company_of.get(e) else [])
        + ([inst[int(e[2:])]["name"]] if e.startswith("i:") and inst[int(e[2:])]["name"] else [])
    )
    pats = [
        re.compile(r"\b" + re.escape(n.strip()) + r"\b", re.I) for n in names if len(n.strip()) >= 4
    ]
    return "; ".join(
        f"{d} (announced {an})" for d, an, tx in manual if any(p.search(tx) for p in pats)
    )


def label(e: str) -> str:
    return inst[int(e[2:])]["symbol"] if e.startswith("i:") else e[2:]


snap: dict[str, dict[date, set[str]]] = defaultdict(lambda: defaultdict(set))
snap_src: dict[tuple[str, date], tuple[str, str, str]] = {}
for comp, asof, pdf, h, pv, iid, sym, ms in snaprows:
    e = (
        f"p:{sym}"
        if sym.startswith("DUMMY")
        else (entity_of(iid, sym, ms) if ms == "MAPPED" else f"s:{sym}")
    )
    snap[COMP[comp]][asof].add(equivalent.get(e, e))
    snap_src[(COMP[comp], asof)] = (pdf, h, pv)
fz = {k: {d: frozenset(v) for d, v in dd.items()} for k, dd in snap.items()}
synth100 = {
    d: fz["N50"][d] | fz["NEXT50"][d] for d in fz.get("N50", {}) if d in fz.get("NEXT50", {})
}  # N100 = N50 + Next 50, same date

derived = walk_back({"N50": n50, "NEXT50": nx50, "MID100": mid}, trs, START, anchor_date)
exp200 = walk_back({"N200x": n200}, trs, START, anchor_date)
exp100 = walk_back({"N100x": n50 | nx50}, trs, START, anchor_date)

recon: dict[str, Any] = {}
for name, w, comps, sn in (
    ("N50_vs_monthly", derived, ["N50"], fz.get("N50", {})),
    ("NEXT50_vs_monthly", derived, ["NEXT50"], fz.get("NEXT50", {})),
    ("MID100_vs_monthly", derived, ["MID100"], fz.get("MID100", {})),
    ("derived_N100_vs_monthly_N100", derived, ["N50", "NEXT50"], fz.get("N100x", {})),
    (
        "derived_N100_vs_N50_plus_NEXT50_same_date",
        derived,
        ["N50", "NEXT50"],
        synth100,
    ),  # PARTIAL: Midcap 100 is not covered
    ("derived_N200_vs_monthly_N200", derived, DERIVED, fz.get("N200x", {})),
    ("explicit_N100_sections_vs_monthly_N100", exp100, ["N100x"], fz.get("N100x", {})),
    ("explicit_N200_sections_vs_monthly_N200", exp200, ["N200x"], fz.get("N200x", {})),
):
    recon[name] = reconcile(w, comps, sn, "PARTIAL" if "same_date" in name else "FULL", same_issuer)

# derived union vs the walk that uses ONLY the explicit Nifty 200 sections, at every date either changes
cross = []
for d in sorted({s.day for s in derived.steps} | {s.day for s in exp200.steps} | {START}):
    du, ex = state_on(derived, DERIVED, d), state_on(exp200, ["N200x"], d)
    cross.append(
        {
            "date": d,
            "derived": len(du),
            "explicit": len(ex),
            "only_derived": sorted(du - ex),
            "only_explicit": sorted(ex - du),
        }
    )

# blocks: only where an independent snapshot disagrees, and only for the entities that disagree
blocks: dict[str, list[tuple[date, date]]] = defaultdict(list)
union_rows = combine_rows(
    recon["derived_N200_vs_monthly_N200"], recon["derived_N100_vs_N50_plus_NEXT50_same_date"]
)
for e, spans in block_windows(union_rows, START, anchor_date).items():
    blocks[e].extend(spans)


def merge(spans: list[tuple[date, date]]) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


blocks = defaultdict(
    list, hand_over_spans(blocks, handover)
)  # a span belongs to the instrument trading then
for e in list(blocks):
    spans = merge(blocks[e])
    if e.startswith(
        "p:"
    ):  # a placeholder is not tradable: nothing to block (the mismatch is still reported)
        del blocks[e]
        continue
    if e.startswith("i:"):  # a security cannot be a member before it listed or after its last trade
        lo_cap, hi_cap = inst[int(e[2:])]["listed_on"], inst[int(e[2:])]["delisted_on"]
        spans = [
            (max(lo, lo_cap) if lo_cap else lo, min(hi, hi_cap) if hi_cap else hi)
            for lo, hi in spans
        ]
        spans = [(lo, hi) for lo, hi in spans if lo < hi]
    blocks[e] = spans

events = union_events(derived, DERIVED)
ivs = hand_over_isin_changes(intervals_from(derived, DERIVED, START, anchor_date), handover)

# ---------------- outputs ----------------
a.out.mkdir(parents=True, exist_ok=True)


def write_csv(name: str, data: list[dict[str, Any]]) -> None:
    with (a.out / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]) if data else ["empty"])
        w.writeheader()
        w.writerows(data)


def tradable(e: str) -> bool:
    return e.startswith("i:")


write_csv(
    "membership_events.csv",
    [
        {
            "effective_from": ev.day,
            "entity": ev.entity,
            "symbol": label(ev.entity),
            "event_type": ev.kind,
            "previous_state": "NOT_MEMBER" if ev.kind == "ADD" else "MEMBER",
            "new_state": "MEMBER" if ev.kind == "ADD" else "NOT_MEMBER",
            "announcement_date": ev.announced,
            "tradable": tradable(ev.entity),
            "source_docs": "; ".join(sorted({x.doc_id for x in ev.sources})),
            "source_sections": "; ".join(
                sorted({f"{x.component}/{x.section}/p{x.page}" for x in ev.sources})
            ),
            "source_hashes": "; ".join(sorted({x.source_hash for x in ev.sources})),
            "parser_versions": "; ".join(sorted({x.parser_version for x in ev.sources})),
            "verification_status": "PROVISIONAL",
            "effective_before_announcement": ev.day < ev.announced,
        }
        for ev in events
    ],
)
write_csv(
    "membership_intervals.csv",
    [
        {
            "entity": i.entity,
            "symbol": label(i.entity),
            "instrument_id": i.entity[2:] if tradable(i.entity) else "",
            "tradable": tradable(i.entity),
            "kind": {"i": "INSTRUMENT", "s": "UNMAPPED_SYMBOL", "p": "PLACEHOLDER"}[i.entity[0]],
            "start": i.start,
            "end_exclusive": i.end or "",
            "start_basis": i.start_basis,
            "blocked_spans": "; ".join(f"{lo}..{hi}" for lo, hi in blocks.get(i.entity, [])),
            "verification_status": "PROVISIONAL",
        }
        for i in ivs
    ],
)

exc: list[dict[str, Any]] = []
for t in derived.unplaced + exp200.unplaced + exp100.unplaced:
    exc.append(
        {
            "kind": "UNDATED_TRANSITION",
            "entity": t.entity,
            "symbol": t.symbol,
            "component": t.component,
            "action": t.action,
            "doc_id": t.doc_id,
            "announced": t.announced,
            "effective": "",
            "detail": "the release row carries no effective date: NOT applied; a person must take the date from the source document",
            "blocked": "; ".join(f"{lo}..{hi}" for lo, hi in blocks.get(t.entity, [])),
        }
    )
for w, nm in ((derived, "derived"), (exp200, "explicit_N200"), (exp100, "explicit_N100")):
    for t in w.future:
        exc.append(
            {
                "kind": "FUTURE_DATED_TRANSITION",
                "entity": t.entity,
                "symbol": t.symbol,
                "component": t.component,
                "action": t.action,
                "doc_id": t.doc_id,
                "announced": t.announced,
                "effective": t.effective,
                "detail": f"effective after the {anchor_date} anchor ({nm} walk): not applied",
                "blocked": "",
            }
        )
    for d_ in w.discrepancies:
        exc.append(
            {
                "kind": f"WALK_{d_['kind']}",
                "entity": d_["entity"],
                "symbol": label(d_["entity"]),
                "component": d_["component"],
                "action": "",
                "doc_id": "",
                "announced": "",
                "effective": d_["day"],
                "detail": f"{nm} walk: the transition is inconsistent with the state it was undone from",
                "blocked": "",
            }
        )
for e, spans in sorted(blocks.items()):
    exc.append(
        {
            "kind": "SNAPSHOT_MISMATCH_BLOCK",
            "entity": e,
            "symbol": label(e),
            "component": "N200",
            "action": "",
            "doc_id": "",
            "announced": "",
            "effective": "",
            "detail": "reconstruction disagrees with an independent snapshot; blocked from the last agreeing snapshot to the next. Unparsed releases mentioning it: "
            + (manual_leads(e) or "none found"),
            "blocked": "; ".join(f"{lo}..{hi}" for lo, hi in spans),
        }
    )
for i in ivs:
    if not tradable(i.entity):
        exc.append(
            {
                "kind": "PLACEHOLDER_NOT_TRADABLE"
                if i.entity[0] == "p"
                else "MEMBER_WITHOUT_INSTRUMENT",
                "entity": i.entity,
                "symbol": label(i.entity),
                "component": "N200",
                "action": "",
                "doc_id": "",
                "announced": "",
                "effective": i.start,
                "detail": f"member {i.start}..{i.end or anchor_date}: no tradable instrument, so the investable universe is incomplete on these dates",
                "blocked": "",
            }
        )
for rv in unmatched_revocations:
    exc.append(
        {
            "kind": "REVOCATION_UNMATCHED",
            "entity": "",
            "symbol": rv.symbol,
            "component": rv.component,
            "action": rv.action,
            "doc_id": rv.doc_id,
            "announced": "",
            "effective": rv.effective,
            "detail": f"{rv.authority_doc} revokes a change that no stored transition matches",
            "blocked": "",
        }
    )
for rep in unmatched_replacements:
    exc.append(
        {
            "kind": "REPLACEMENT_UNMATCHED",
            "entity": f"p:{rep.placeholder}",
            "symbol": rep.symbol,
            "component": "N200",
            "action": "",
            "doc_id": rep.evidence_doc,
            "announced": "",
            "effective": rep.listed_on,
            "detail": f"{rep.symbol} replaces {rep.placeholder} on {rep.listed_on} but no stored inclusion/exclusion pair matches",
            "blocked": "",
        }
    )
write_csv(
    "membership_entity_equivalence.csv",
    [
        {"from": src, "to": rec["to"], "symbol": rec["symbol"], "reason": rec["reason"],
         "review_decision_ids": ";".join(str(i) for i in rec["review_decision_ids"])}
        for rec in equiv_records
        for src in rec["from"]
    ],
)  # fmt: skip
write_csv("membership_exceptions.csv", exc)
authority_hash = {r[1]: r[7] for r in revrows}
write_csv(
    "membership_cancellations.csv",
    [
        {
            "effective_from": tr.effective,
            "symbol": tr.symbol,
            "component": rv.component,
            "cancelled_action": tr.action,
            "announced_in": tr.doc_id,
            "announced_on": tr.announced,
            "announcement_hash": tr.source_hash,
            "revoked_by": rv.authority_doc,
            "revocation_hash": authority_hash.get(rv.authority_doc, ""),
        }
        for rv, tr in cancelled
    ],
)


def counts_at(d: date) -> dict[str, int]:
    u = state_on(derived, DERIVED, d)
    k = Counter(e[0] for e in u)
    return {
        "total": len(u),
        "tradable_instruments": k["i"],
        "unmapped_symbols": k["s"],
        "placeholders": k["p"],
    }


change_days = sorted({START, anchor_date, *(s.day for s in derived.steps)})
month_ends = sorted({d for dd in fz.values() for d in dd if START <= d <= anchor_date})


def summ(rs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "snapshots_compared": len(rs),
        "exact_agreement": sum(
            1 for r in rs if not r["only_in_snapshot"] and not r["only_in_reconstruction"]
        ),
        "total_entity_differences": sum(
            len(r["only_in_snapshot"]) + len(r["only_in_reconstruction"]) for r in rs
        ),
    }


(a.out / "membership_reconciliation.json").write_text(
    json.dumps(
        {
            "window": [str(START), str(anchor_date)],
            "script_version": SCRIPT_VERSION,
            "anchor": {
                "as_of": anchor_date,
                "N50": len(n50),
                "NEXT50": len(nx50),
                "MID100": len(mid),
                "explicit_N200": len(n200),
                "derived_equals_explicit": (n50 | nx50 | mid) == n200,
            },
            "summary": {k: summ(v) for k, v in recon.items()},
            "counts_by_date_derived_union_NOT_forced_to_200": {
                str(d): counts_at(d) for d in sorted(set(change_days) | set(month_ends))
            },
            "derived_vs_explicit_N200_sections_by_change_date": [
                {**x, "date": str(x["date"])}
                for x in cross
                if x["only_derived"] or x["only_explicit"]
            ],
            "derived_vs_explicit_N200_sections_dates_compared": len(cross),
            "walk_discrepancies": {
                nm: len(w.discrepancies)
                for nm, w in (
                    ("derived", derived),
                    ("explicit_N200", exp200),
                    ("explicit_N100", exp100),
                )
            },
            "comparisons": {
                k: [
                    {**r, "date": str(r["date"])}
                    for r in v
                    if r["only_in_snapshot"] or r["only_in_reconstruction"]
                ]
                for k, v in recon.items()
            },
        },
        indent=2,
        default=str,
    )
    + "\n"
)

used_docs = {t.doc_id for t in trs if t.effective is None or START < t.effective <= anchor_date}
(a.out / "membership_evidence_manifest.json").write_text(
    json.dumps(
        {
            "script_version": SCRIPT_VERSION,
            "hierarchy": [
                "official NSE Indices constituent-change announcements",
                "official current constituent snapshots (anchor)",
                "instrument identity and ISIN records (no automatic mapping)",
                "monthly constituent PDFs (independent checkpoints)",
                "derived N200 = N50 + Next 50 + Midcap 100",
            ],
            "anchor_snapshots": {
                idx: {
                    "as_of": anchor_date,
                    "members": len(m),
                    "lake_dataset": ds,
                    "lake_manifests": [
                        json.loads(Path(p).read_text()) | {"path": p}
                        for p in sorted(
                            glob.glob(str(a.lake / f"raw/niftyindices/{ds}/dt=*/v*.manifest.json"))
                        )[-1:]
                    ],
                }
                for idx, m, ds in (
                    ("NIFTY50", n50, "nifty50_list"),
                    ("NIFTYNEXT50", nx50, "niftynext50_list"),
                    ("NIFTYMIDCAP100", mid, "niftymidcap100_list"),
                    ("NIFTY200", n200, "nifty200_list"),
                )
            },
            "press_releases_used": sorted(
                (
                    {
                        "doc_id": d,
                        "source_url": doc_url[d],
                        "source_hash": next(t.source_hash for t in trs if t.doc_id == d),
                        "announced": str(next(t.announced for t in trs if t.doc_id == d)),
                        "parser_version": next(t.parser_version for t in trs if t.doc_id == d),
                        "rows": sum(1 for t in trs if t.doc_id == d),
                    }
                    for d in used_docs
                ),
                key=lambda x: (x["announced"], x["doc_id"]),
            ),
            "monthly_snapshots_used": [
                {
                    "component": k[0],
                    "as_of": str(k[1]),
                    "pdf_name": v[0],
                    "pdf_hash": v[1],
                    "parser_version": v[2],
                }
                for k, v in sorted(snap_src.items(), key=lambda kv: (kv[0][0], kv[0][1]))
                if START <= k[1] <= anchor_date
            ],
        },
        indent=2,
        default=str,
    )
    + "\n"
)

blocked_entities = {e for e, s in blocks.items() if s}
months = []
for d in month_ends if month_ends else change_days:
    cnt = counts_at(d)
    blk = [e for e in blocked_entities if any(lo <= d < hi for lo, hi in blocks[e])]
    months.append(
        {
            "date": str(d),
            **cnt,
            "blocked_entities": len(blk),
            "status": "CLEAN"
            if not blk and not cnt["unmapped_symbols"] and not cnt["placeholders"]
            else "INCOMPLETE",
        }
    )
(a.out / "membership_coverage.json").write_text(
    json.dumps(
        {
            "window": [str(START), str(anchor_date)],
            "declared_in_database": False,
            "verification_status": "PROVISIONAL: nothing here is person-verified, and no coverage has been declared in index_membership_coverage",
            "independent_checks_by_period": {
                "N50 and Next 50 monthly constituents": [str(min(fz["N50"])), str(max(fz["N50"]))],
                "N100/N200/Midcap 100 monthly constituents": [
                    str(min(fz["N200x"])),
                    str(max(fz["N200x"])),
                ],
                "after the last Midcap 100 / N200 monthly snapshot": "Midcap 100 membership rests on press releases and the current snapshot only (the walk's agreement with the anchor is the only check)",
            },
            "blocked_entities": {
                e: [[str(lo), str(hi)] for lo, hi in s] for e, s in sorted(blocks.items()) if s
            },
            "months": months,
            "status_counts": dict(Counter(m["status"] for m in months)),
            "note": "CLEAN = no blocked entity and no member without a tradable instrument on that date. INCOMPLETE is not 'wrong'; it says what cannot be established.",
        },
        indent=2,
        default=str,
    )
    + "\n"
)

print(
    json.dumps(
        {
            "anchor": anchor_date,
            "derived_equals_explicit_N200_now": (n50 | nx50 | mid) == n200,
            "events": len(events),
            "intervals": len(ivs),
            "walk_discrepancies": {
                nm: len(w.discrepancies)
                for nm, w in (
                    ("derived", derived),
                    ("explicit_N200", exp200),
                    ("explicit_N100", exp100),
                )
            },
            "unplaced": len(derived.unplaced),
            "future": len(derived.future),
            "reconciliation": {k: summ(v) for k, v in recon.items()},
            "blocked_entities": {
                e: [[str(lo), str(hi)] for lo, hi in s] for e, s in blocks.items() if s
            },
            "coverage_status_counts": dict(Counter(m["status"] for m in months)),
        },
        indent=1,
        default=str,
    )
)
