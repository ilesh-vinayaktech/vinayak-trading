# ruff: noqa: E501  (evidence strings; this is a script, not library code)
"""READ-ONLY classification of every symbol in the Nifty membership releases that has no instrument.

Writes evidence and PROPOSALS only. It never touches the instrument master, aliases or membership:
a mapping enters the authoritative tables only after a person reviews it. ISIN continuity is strong
evidence, not proof (symbols are reused, ISINs change, mergers create new securities), so a proposal
carries its evidence and a confidence, and anything the evidence does not settle stays UNRESOLVED.

usage: classify_unmapped_symbols.py --db postgresql://... --lake data/lake --out docs/stage4/symbol_classification"""

import argparse
import csv
import difflib
import glob
import io
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import psycopg

from algo.data.delisted import successors

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--out", type=Path, default=Path("docs/stage4/symbol_classification"))
ap.add_argument("--research-start", default="2020-10-01")  # first possible signal date (warm-up)
a = ap.parse_args()
RESEARCH_START = date.fromisoformat(a.research_start)


def read_csv_bytes(b: bytes) -> list[dict[str, str]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(b))
        b = z.read(z.namelist()[0])
    except zipfile.BadZipFile:
        pass
    rows = csv.reader(io.StringIO(b.decode("latin1")))
    head = [h.strip().upper() for h in next(rows)]
    return [dict(zip(head, (c.strip() for c in r), strict=False)) for r in rows if r]


def latest(dirpath: str) -> bytes:
    return Path(sorted(glob.glob(f"{dirpath}/v*.bin"))[-1]).read_bytes()


# ---- evidence from the exchange files: when each symbol traded and under which ISIN ----------
seen: dict[str, dict[str, Any]] = defaultdict(
    lambda: {"first": None, "last": None, "legacy": 0, "modern": 0, "isins": {}}
)


def touch(sym: str, day: str, era: str, isin: str | None) -> None:
    e = seen[sym]
    e["first"] = min(filter(None, [e["first"], day]))
    e["last"] = max(filter(None, [e["last"], day]))
    e[era] += 1
    if isin:
        lo, hi = e["isins"].get(isin, (day, day))
        e["isins"][isin] = (min(lo, day), max(hi, day))


for d in sorted(glob.glob(str(a.lake / "raw/nse/bhav_legacy/dt=*"))):
    day = d.rsplit("dt=", 1)[1]
    for r in read_csv_bytes(latest(d)):
        if r.get("SERIES") == "EQ":
            touch(r["SYMBOL"], day, "legacy", r.get("ISIN") or None)
for d in sorted(glob.glob(str(a.lake / "raw/nse/bhav/dt=*"))):
    day = d.rsplit("dt=", 1)[1]
    for r in read_csv_bytes(latest(d)):
        if r.get("SERIES") == "EQ":
            touch(r["SYMBOL"], day, "modern", None)
last_modern = max(e["last"] for e in seen.values() if e["modern"])

# ---- evidence from the database (read-only) ---------------------------------------------------
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    inst = {
        r[0]: {
            "id": r[0],
            "symbol": r[1],
            "isin": r[2],
            "name": r[3],
            "status": r[4],
            "listed": r[5],
            "delisted": r[6],
        }
        for r in c.execute(
            "SELECT instrument_id, symbol, isin, name, status, listed_on, delisted_on FROM instrument"
        )
    }
    alias: dict[str, list[tuple[int, date, date | None]]] = defaultdict(list)
    for iid, sym, vf, vt in c.execute(
        "SELECT instrument_id, source_symbol, valid_from, valid_to FROM instrument_alias WHERE source='nse'"
    ):
        alias[sym].append((iid, vf, vt))
    bars = {
        r[0]: (r[1], r[2], r[3])
        for r in c.execute(
            "SELECT instrument_id, count(*), min(ts)::date, max(ts)::date FROM bar_1d GROUP BY 1"
        )
    }
    rel = c.execute(
        """SELECT symbol,
                  bool_or(mapping_status='PLACEHOLDER_SECURITY') AS placeholder,
                  count(*), min(effective_from), max(effective_from),
                  count(*) FILTER (WHERE effective_from >= %s),
                  count(*) FILTER (WHERE action='INCLUDED'), count(*) FILTER (WHERE action='EXCLUDED'),
                  string_agg(DISTINCT company, ' | '), string_agg(DISTINCT component, ','),
                  bool_or(raw_text ~* 'merg|amalgam|arrangement|demerg|scheme of'),
                  count(*) FILTER (WHERE component IS NOT NULL),
                  count(*) FILTER (WHERE component IS NOT NULL AND (effective_from >= %s OR effective_from IS NULL))
           FROM index_release_row WHERE mapping_status IN ('UNMAPPED_SYMBOL','PLACEHOLDER_SECURITY')
           GROUP BY symbol ORDER BY symbol""",
        (RESEARCH_START, RESEARCH_START),
    ).fetchall()
    mapped = c.execute(
        """SELECT r.symbol, r.instrument_id, count(*), min(r.effective_from), max(r.effective_from)
           FROM index_release_row r WHERE r.mapping_status='MAPPED' AND r.component IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2"""
    ).fetchall()
    fv_split: dict[int, list[str]] = defaultdict(list)
    for iid, ex, subj in c.execute(
        "SELECT instrument_id, ex_date, subject FROM corporate_action WHERE kind='split' AND status='ok' AND subject ILIKE '%face value%'"
    ):
        fv_split[iid].append(f"{ex}: {subj}")
    # the SAME rename/merger-candidate rule delisted.py uses (name's first word + alias starting near the last trade)
    succ_map: dict[str, list[str]] = {}
    for r_ in rel:
        e_ = seen.get(r_[0])
        if e_ and r_[8]:
            succ_map[r_[0]] = successors(c, r_[8].split(" | ")[0], date.fromisoformat(e_["last"]))

by_symbol: dict[str, list[int]] = defaultdict(list)
by_isin: dict[str, list[int]] = defaultdict(list)
for i in inst.values():
    by_symbol[i["symbol"]].append(i["id"])
    if i["isin"]:
        by_isin[i["isin"]].append(i["id"])


def norm(n: str) -> str:
    return " ".join(
        re.sub(
            r"\b(ltd|limited|the|of|and|co|corp|corporation|india|pvt|private)\b|[^a-z0-9 ]",
            " ",
            n.lower(),
        ).split()
    )


rows_out: list[dict[str, Any]] = []
cands: list[dict[str, Any]] = []
for (
    sym,
    placeholder,
    n,
    mn,
    mx,
    n_rw,
    n_inc,
    n_exc,
    companies,
    comps,
    merger_txt,
    n_fam,
    n_fam_rw,
) in rel:
    ev = seen.get(sym)
    isins = dict(sorted(ev["isins"].items(), key=lambda kv: kv[1])) if ev else {}
    same = sorted(set(by_symbol.get(sym, [])) | {x[0] for x in alias.get(sym, [])})
    notes: list[str] = []
    cat, conf, cand, evidence_kind = "UNRESOLVED", "LOW", None, ""

    if placeholder:
        cat, conf = "PLACEHOLDER", "HIGH"
        notes.append(
            "release names a dummy/placeholder security: not a tradable instrument, keep out of the instrument master"
        )
    elif same:
        cand = same[0]
        i = inst[cand]
        if isins and i["isin"] and i["isin"] not in isins:
            cat, conf, evidence_kind = (
                "REPLACED_ISIN",
                "MEDIUM",
                "symbol matches an instrument but its ISIN differs from the ISIN traded under this symbol",
            )
            notes.append(
                f"exchange files show ISIN(s) {list(isins)}; master has {i['isin']}: symbol reuse or ISIN change, legal-entity continuity unproven"
            )
        elif i["status"] == "active":
            cat, conf = "ACTIVE_SAME_ISIN", "HIGH" if isins and i["isin"] in isins else "MEDIUM"
            evidence_kind = "same symbol" + (
                " and same ISIN in exchange files"
                if conf == "HIGH"
                else ", no independent ISIN evidence"
            )
            ranges = [(vf, vt) for x, vf, vt in alias.get(sym, []) if x == cand]
            notes.append(
                f"alias validity {[(str(x), str(y) if y else None) for x, y in ranges]} vs release rows {mn}..{mx}: "
                + ("covers" if ranges and ranges[0][0] <= mn else "does NOT cover them (alias gap)")
            )
        else:
            cat, conf, evidence_kind = (
                "DELISTED_WITH_PRICES",
                "MEDIUM",
                "same symbol, instrument is not active",
            )
    elif isins:
        succ = sorted({iid for isin in isins for iid in by_isin.get(isin, [])})
        if succ:
            y = succ[0]
            cand, cat = y, "RENAMED_SAME_ISIN"
            fy = str(bars[y][1]) if y in bars else None
            gap = (date.fromisoformat(fy) - date.fromisoformat(ev["last"])).days if fy else None
            overlap = gap is not None and gap < 0
            conf = "LOW" if overlap or gap is None else ("HIGH" if gap <= 31 else "MEDIUM")
            evidence_kind = "ISIN also belongs to another instrument; this symbol stopped trading before that one's bars begin"
            if overlap:
                cat, evidence_kind = (
                    "UNRESOLVED",
                    "ISIN shared but the two symbols traded at the same time",
                )
                notes.append(
                    f"symbol traded until {ev['last']} but instrument {y} has bars from {fy}: overlapping, not a clean rename"
                )
            notes.append(
                f"symbol last traded {ev['last']}; successor first bar {fy} (gap {gap} days); legal-entity vs tradable continuity not proven"
            )
        else:
            cat, conf, evidence_kind = (
                (
                    "MERGED_OR_AMALGAMATED",
                    "LOW",
                    "textual merger/amalgamation/arrangement evidence in the release; no instrument holds this ISIN",
                )
                if merger_txt
                else (
                    "DELISTED_NO_PRICES",
                    "MEDIUM",
                    "traded in the exchange files, ISIN not in the master",
                )
            )
            if cat == "MERGED_OR_AMALGAMATED":
                notes.append("successor and consideration NOT identified: investigate")
    elif ev:
        cat, conf, evidence_kind = (
            ("MERGED_OR_AMALGAMATED", "LOW", "textual merger evidence; traded without ISIN data")
            if merger_txt
            else (
                "DELISTED_NO_PRICES",
                "LOW",
                "traded in the exchange files; no ISIN available for the period",
            )
        )
    else:
        notes.append("never appears in any stored exchange file")

    if cat in ("DELISTED_NO_PRICES", "MERGED_OR_AMALGAMATED") and ev and ev["last"] == last_modern:
        cat, conf = "UNRESOLVED", "LOW"
        notes.append(
            "still trading in the latest exchange file yet absent from the master: inconsistent, investigate"
        )

    if cat == "REPLACED_ISIN" and cand and fv_split.get(cand):
        notes.append(
            f"corroboration (not proof): candidate has a verified face-value split {fv_split[cand]}; an ISIN change normally accompanies it; person must confirm the ISIN change date"
        )
    if cat in ("DELISTED_NO_PRICES", "MERGED_OR_AMALGAMATED") and succ_map.get(sym):
        sx = succ_map[sym]
        cat, conf = "UNRESOLVED", "LOW"
        cand = next(x[0] for x in alias[sx[0]])
        evidence_kind = f"rename/merger candidate(s) by name and timing ONLY: {sx}"
        notes.append(
            f"stopped trading {ev['last']}; instrument(s) {sx} start within [-30,+120] days under a similar name: rename, merger or coincidence is NOT established"
        )
    if mn is None:
        notes.append(
            "release rows have NO effective date: they cannot map through alias validity until a date is taken from the document"
        )
    # name-only suggestion for unresolved cases: never decides anything
    if cat == "UNRESOLVED" and cand is None and companies and not succ_map.get(sym):
        target = norm(companies.split(" | ")[0])
        best = max(
            (
                (difflib.SequenceMatcher(None, target, norm(i["name"])).ratio(), i["id"])
                for i in inst.values()
                if i["name"]
            ),
            default=(0.0, None),
        )
        if best[0] >= 0.9:
            cand, evidence_kind = (
                best[1],
                f"company-name similarity {best[0]:.2f} ONLY (no ISIN/symbol evidence)",
            )

    recov = "NONE"
    if cat in ("DELISTED_NO_PRICES", "MERGED_OR_AMALGAMATED", "UNRESOLVED") and ev:
        recov = "+".join(
            x for x, k in (("MODERN_RAW_LAKE", "modern"), ("LEGACY_ARCHIVE", "legacy")) if ev[k]
        )
    cb = bars.get(cand) if cand else None
    rows_out.append(
        {
            "symbol": sym,
            "category": cat,
            "confidence": conf,
            "review_status": "UNREVIEWED",
            "scope": "NIFTY200_FAMILY" if n_fam else "OTHER_INDEX_ONLY",
            "family_rows": n_fam,
            "family_rows_since_research_start": n_fam_rw,
            "release_rows": n,
            "included": n_inc,
            "excluded": n_exc,
            "first_release_effective": mn,
            "last_release_effective": mx,
            "rows_since_research_start": n_rw,
            "touches_research_window": n_fam_rw > 0,
            "first_exchange_file": ev["first"] if ev else "",
            "last_exchange_file": ev["last"] if ev else "",
            "sessions_legacy": ev["legacy"] if ev else 0,
            "sessions_modern": ev["modern"] if ev else 0,
            "isins_in_exchange_files": "; ".join(f"{k}[{v[0]}..{v[1]}]" for k, v in isins.items()),
            "release_companies": companies or "",
            "components": comps or "",
            "merger_text_in_release": bool(merger_txt),
            "candidate_instrument_id": cand or "",
            "candidate_symbol": inst[cand]["symbol"] if cand else "",
            "candidate_isin": inst[cand]["isin"] if cand else "",
            "candidate_name": inst[cand]["name"] if cand else "",
            "candidate_status": inst[cand]["status"] if cand else "",
            "candidate_bars": cb[0] if cb else 0,
            "candidate_bar_range": f"{cb[1]}..{cb[2]}" if cb else "",
            "prices_recoverable_from": recov,
            "relation_evidence": evidence_kind,
            "notes": " / ".join(notes),
        }
    )
    if cand and cat != "PLACEHOLDER":
        cands.append(
            {
                "symbol": sym,
                "category": cat,
                "confidence": conf,
                "candidate_instrument_id": cand,
                "candidate_symbol": inst[cand]["symbol"],
                "candidate_isin": inst[cand]["isin"],
                "first_exchange_file": ev["first"] if ev else "",
                "last_exchange_file": ev["last"] if ev else "",
                "first_release_effective": mn,
                "evidence": evidence_kind,
                "review_status": "UNREVIEWED",
                "reviewer": "",
                "reviewed_at": "",
            }
        )


def write(name: str, data: list[dict[str, Any]], fields: list[str]) -> None:
    with (a.out / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(data)


# identity check on the rows that DID map: does the exchange-file ISIN for the symbol agree with the instrument's?
chk = []
for sym, iid, n_, mn_, mx_ in mapped:
    e_ = seen.get(sym)
    isn = dict(e_["isins"]) if e_ else {}
    i_ = inst[iid]
    issuer = lambda x: x[:7]  # noqa: E731 - IN + issuer code: the same issuer keeps it across face-value changes
    if not isn:
        verdict = "NO_ISIN_EVIDENCE"
    elif not i_["isin"]:
        verdict = "INSTRUMENT_ISIN_MISSING"
    elif i_["isin"] in isn:
        verdict = "ISIN_AGREES"
    elif {issuer(x) for x in isn} & {issuer(i_["isin"])}:
        verdict = "ISIN_CHANGED_SAME_ISSUER"
    else:
        verdict = "ISIN_DIFFERS_OTHER_ISSUER"
    chk.append(
        {
            "symbol": sym,
            "instrument_id": iid,
            "instrument_symbol": i_["symbol"],
            "instrument_isin": i_["isin"],
            "exchange_file_isins": "; ".join(isn),
            "release_rows": n_,
            "first_release_effective": mn_,
            "last_release_effective": mx_,
            "verdict": verdict,
        }
    )
a.out.mkdir(parents=True, exist_ok=True)
write("mapped_identity_check.csv", chk, list(chk[0]))
write("symbol_classification.csv", rows_out, list(rows_out[0]))
write("mapping_candidates.csv", cands, list(cands[0]) if cands else [])
write("unresolved.csv", [r for r in rows_out if r["category"] == "UNRESOLVED"], list(rows_out[0]))


def block(rs: list[dict[str, Any]]) -> dict[str, Any]:
    cn = Counter(r["category"] for r in rs)
    return {
        "symbols": len(rs),
        "by_category": dict(sorted(cn.items())),
        "by_category_and_confidence": {
            k: dict(Counter(r["confidence"] for r in rs if r["category"] == k)) for k in sorted(cn)
        },
        "rows_by_category": {
            k: sum(r["release_rows"] for r in rs if r["category"] == k) for k in sorted(cn)
        },
        "family_rows": sum(r["family_rows"] for r in rs),
        "touching_research_window": dict(
            sorted(Counter(r["category"] for r in rs if r["touches_research_window"]).items())
        ),
        "prices_recoverable_from": dict(
            Counter(
                r["prices_recoverable_from"]
                for r in rs
                if r["category"] in ("DELISTED_NO_PRICES", "MERGED_OR_AMALGAMATED", "UNRESOLVED")
            )
        ),
    }


fam = [r for r in rows_out if r["scope"] == "NIFTY200_FAMILY"]
summary = {
    "latest_modern_exchange_file": last_modern,
    "research_start_used": a.research_start,
    "all_symbols": block(rows_out),
    "NIFTY200_FAMILY_symbols (the ones this strategy can depend on)": block(fam),
    "OTHER_INDEX_ONLY_symbols (SME Emerge, Smallcap, Total Market, thematic ...)": block(
        [r for r in rows_out if r["scope"] != "NIFTY200_FAMILY"]
    ),
    "mapped_family_rows_identity_check": dict(Counter(r["verdict"] for r in chk)),
    "mapping_candidates": len(cands),
    "nothing_was_written_to_the_database": True,
}
(a.out / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n"
)
print(json.dumps(summary, indent=2, sort_keys=True, default=str))
