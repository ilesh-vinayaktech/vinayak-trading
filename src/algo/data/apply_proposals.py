# ruff: noqa: E501  (one-line action records are kept readable as literals)
"""PROPOSAL-ONLY application of reviewed decisions. Turns each recorded review decision into the exact
writes a person would have to approve (instrument, alias, successor / continuity records), plus a dry run
of which membership exceptions they would clear. Nothing here writes anywhere: the functions are pure
and every write is described, never executed."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

# Corporate-action relationships stated in the recorded decision notes. ratio = (target shares, source shares).
# Ratios and dates here come from the decision notes / search results, NOT from a primary filing unless said so.
RELATIONSHIPS: dict[str, dict[str, Any]] = {
    "ABIRLANUVO": {"type": "AMALGAMATED_INTO", "target": "GRASIM", "effective": date(2017, 7, 1), "ratio": (15, 10), "basis": "Grasim disclosures: 15 Grasim shares per 10 ABNL; not an alias to ABCAPITAL"},
    "BHARATFIN": {"type": "AMALGAMATED_INTO", "target": "INDUSINDBK", "effective": date(2019, 7, 4), "ratio": (639, 1000), "basis": "IndusInd Bank announcement (effective date and ratio not re-read from the primary page)"},
    "DALMIABHA": {"type": "AMALGAMATED_INTO", "target": "DALBHARAT", "effective": date(2019, 1, 9), "ratio": None, "basis": "scheme of arrangement into Odisha Cement (renamed Dalmia Bharat 2019-04-15); the annual report prints '2:1' without its direction, so no ratio is stored"},
    "PEL": {"type": "MERGED_INTO", "target": "PIRAMALFIN", "effective": date(2025, 9, 16), "ratio": None, "basis": "PEL filing of 2025-09-16 (1:1 ratio not verified, so not stored)"},
    "GSPL": {"type": "AMALGAMATED_INTO", "target": "GUJENERGY", "effective": date(2026, 5, 1), "ratio": (10, 13), "basis": "NSE results filings: scheme effective 2026-05-01; ratio 10 Gujarat Gas per 13 GSPL from search results"},
    "MINDTREE": {"type": "AMALGAMATED_INTO", "target": "LTIM", "effective": date(2022, 11, 14), "ratio": (73, 100), "basis": "L&T Infotech scheme: effective date and ratio from search results, not a primary filing"},
    "HEXAWARE": {"type": "SAME_ISSUER_NEW_INSTRUMENT", "target": "HEXT", "effective": date(2025, 2, 19), "ratio": None, "basis": "NSE circular CML66715: same issuer relisted by IPO as a new security"},
}  # fmt: skip
# Delisting dates that a primary document states (NOT archive boundaries): MINDTREE NSE circular 1369/2022
# (suspended from 2022-11-23); HEXAWARE delisting FAQ (NSE delisting 2020-11-09).
EVIDENCED_DELISTING = {"MINDTREE": date(2022, 11, 23), "HEXAWARE": date(2020, 11, 9)}

_DATES = re.compile(r"(\d{4}-\d{2}-\d{2})\s*\.\.\s*(\d{4}-\d{2}-\d{2})")
_ISIN = re.compile(r"(INE[0-9A-Z]{9})")


def parse_facts(context: Mapping[str, str]) -> dict[str, Any]:
    """first/last exchange-file date and the ISIN seen, from a review item's own context."""
    m = _DATES.search(context.get("Exchange files", ""))
    i = _ISIN.search(context.get("ISINs seen") or "")
    return {
        "first": date.fromisoformat(m.group(1)) if m else None,
        "last": date.fromisoformat(m.group(2)) if m else None,
        "isin": i.group(1) if i else None,
    }


def _one(item_id: str, rec: Mapping[str, Any], kind: str, summary: str, actions: list[dict[str, Any]],
         evidence: Sequence[str], caveats: Sequence[str] = (), status: str = "PROPOSED",
         plan: Sequence[str] = ()) -> dict[str, Any]:  # fmt: skip
    return {
        "item_id": item_id, "decision_id": rec["decision_id"], "decision": rec["decision"],
        "reviewer": rec["reviewer"], "status": status, "kind": kind, "summary": summary,
        "actions": actions, "evidence": [rec["evidence_ref"], *evidence], "caveats": list(caveats),
        "plan_if_approved": list(plan),
    }  # fmt: skip


def _instrument_action(symbol: str, facts: Mapping[str, Any]) -> dict[str, Any]:
    return {"table": "instrument", "operation": "INSERT", "values": {
        "symbol": symbol, "isin": facts["isin"], "status": "delisted",
        "listed_on": None,  # a listing date is a verified fact: NULL until evidenced, never the archive start
        "first_observed_on": facts["first"], "last_traded_on": facts["last"],
        "delisted_on": EVIDENCED_DELISTING.get(symbol),
    }}  # fmt: skip


def _alias_action(symbol: str, instrument: Any, facts: Mapping[str, Any]) -> dict[str, Any]:
    end = facts["last"] + timedelta(days=1) if facts["last"] else None  # end-exclusive
    return {"table": "instrument_alias", "operation": "INSERT", "values": {
        "instrument_id": instrument, "source": "nse", "source_symbol": symbol,
        "valid_from": facts["first"], "valid_from_basis": "FIRST_OBSERVED",
        "valid_to": end, "valid_to_basis": "LAST_OBSERVED",
    }}  # fmt: skip


def _relationship_action(symbol: str, source: Any, rec: Mapping[str, Any]) -> dict[str, Any]:
    r = RELATIONSHIPS[symbol]
    num, den = r["ratio"] or (None, None)
    return {"table": "corporate_action_relationship", "operation": "INSERT", "values": {
        "relationship_type": r["type"], "source_instrument_id": source, "target_symbol": r["target"],
        "appointed_date": None, "effective_date": r["effective"], "ratio_num": num, "ratio_den": den,
        "known_at": None, "evidence": [rec["evidence_ref"], r["basis"]],
        "verification_status": "PROVISIONAL", "review_decision_id": rec["decision_id"],
    }}  # fmt: skip


def symbol_proposal(
    symbol: str, rec: Mapping[str, Any], facts: Mapping[str, Any], existing: Mapping[str, Any]
) -> dict[str, Any]:  # fmt: skip
    """`existing` = {"instrument": {...}|None, "aliases": [(valid_from, valid_to), ...], "dependents": {...}}."""
    item_id, decision = f"symbol:{symbol}", rec["decision"]
    inst, aliases = existing["instrument"], existing["aliases"]
    if decision == "KEEP_PLACEHOLDER":
        return _one(item_id, rec, "PLACEHOLDER", f"{symbol} is a non-tradable index placeholder: no instrument, no alias, no ISIN",
                    [], ["membership: reviewed placeholder replacement record"])  # fmt: skip
    if decision == "CONFIRM_MAPPING":
        start = rec["effective_date"]
        if any(a[0] == start for a in aliases):
            return _one(item_id, rec, "ALIAS_ALREADY_PRESENT", f"alias {symbol} -> instrument {inst['id']} valid from {start} is already in the master", [], [])  # fmt: skip
        end = facts["last"] + timedelta(days=1) if facts["last"] else None
        act = {"table": "instrument_alias", "operation": "INSERT", "values": {"instrument_id": inst["id"], "source": "nse", "source_symbol": symbol, "valid_from": start, "valid_from_basis": "EVIDENCED", "valid_to": end, "valid_to_basis": "LAST_OBSERVED" if end else None}}  # fmt: skip
        return _one(
            item_id,
            rec,
            "SYMBOL_ALIAS",
            f"map {symbol} to instrument {inst['id']} from {start}",
            [act],
            [],
        )
    if decision == "SET_EFFECTIVE_DATE":  # an ISIN change: two securities of one issuer
        change = rec["effective_date"]
        deps = existing.get("dependents", {})
        blockers = [
            f"instrument {inst['id']} (new ISIN) already owns {deps.get('bar_1d', (0, 0))[1]} bars and "
            f"{deps.get('corporate_action', (0, 0))[1]} corporate actions dated before {change} that belong to the old ISIN; "
            f"it has {deps.get('index_release_row', (0, 0))[0]} mapped component release rows "
            f"({deps.get('index_release_row', (0, 0))[1]} dated before the change) and "
            f"{deps.get('unmapped_release_rows', (0, 0))[0]} unmapped component rows that would map to the old ISIN once its alias exists",
            "its alias starts before the change date: two aliases of one symbol may not overlap (enforced by migration 024)",
            "decision needed: confirm that the old ISIN is a separate instrument that owns observations up to the day before the change",
        ]  # fmt: skip
        if deps.get("reader_check") == "PASS":
            blockers.append("reader check PASSED on the real data (scripts/verify_nestleind_identity.py): the issuer-scoped read equals today's read in every adjustment mode")  # fmt: skip
        else:
            blockers.append("downstream readers must follow a SAME_ISSUER_ISIN_CHANGE relationship before any row is moved")  # fmt: skip
        plan = [
            f"INSERT instrument (old ISIN {facts['isin']}), first_observed_on {facts['first']}, last_traded_on = day before {change}, listed_on NULL",
            f"INSERT alias {symbol} -> old instrument, valid_to {change} (EVIDENCED: NSE circular CML60084)",
            f"MOVE bars, corporate actions and release rows dated before {change} from instrument {inst['id']} to the old instrument, with pre/post counts and a duplicate check",
            f"UPDATE alias of instrument {inst['id']}: valid_from {change} (EVIDENCED)",
            "INSERT corporate_action_relationship SAME_ISSUER_ISIN_CHANGE old -> new, effective_date " + str(change),
            "make the adjusted-bars reader and the membership comparison follow that relationship",
        ]  # fmt: skip
        return _one(item_id, rec, "BLOCKED_IDENTITY_MODEL", f"{symbol}: two ISIN identities linked by the split on {change}: BLOCKED until the overlap with instrument {inst['id']} is resolved",
                    [], [], blockers, status="BLOCKED", plan=plan)  # fmt: skip
    # KEEP_SEPARATE / NO_SUCCESSOR: the security stays its own historical instrument
    actions: list[dict[str, Any]] = []
    if inst is None:
        actions += [_instrument_action(symbol, facts), _alias_action(symbol, "<new>", facts)]
        source: Any = "<new>"
    else:
        source = inst["id"]
        if inst["isin"] is None and facts["isin"]:
            actions.append({"table": "instrument", "operation": "UPDATE", "values": {"instrument_id": inst["id"], "isin": facts["isin"]}})  # fmt: skip
        if not aliases:
            actions.append(_alias_action(symbol, inst["id"], facts))
    if symbol in RELATIONSHIPS:
        actions.append(_relationship_action(symbol, source, rec))
    if not actions:
        return _one(
            item_id, rec, "NO_CHANGE_NEEDED", f"{symbol} is already complete in the master", [], []
        )
    kind = "HISTORICAL_INSTRUMENT" if inst is None else "COMPLETE_EXISTING_INSTRUMENT"
    return _one(item_id, rec, kind, f"{symbol} stays its own historical instrument; any successor is an effective-dated relationship, not an alias", actions, [])  # fmt: skip


def membership_proposal(
    item_id: str, rec: Mapping[str, Any], reflected_in: Sequence[str], still_open: bool
) -> dict[str, Any]:  # fmt: skip
    """A membership decision never writes a table: it is reflected in the reconstruction through reviewed config."""
    cav = ["a matching exception still exists in the adopted baseline"] if still_open else []
    return _one(item_id, rec, "NO_WRITE_REFLECTED_IN_RECONSTRUCTION",
                f"already applied in membership revision 3 via {', '.join(reflected_in)}", [], list(reflected_in), cav)  # fmt: skip


def dry_run(
    exceptions: Sequence[Mapping[str, str]], intervals: Sequence[Mapping[str, str]],
    proposals: Sequence[Mapping[str, Any]], anchor: date,
) -> list[dict[str, Any]]:  # fmt: skip
    """For each MEMBER_WITHOUT_INSTRUMENT exception: does a proposed alias cover EVERY day of the entity's
    member spans (alias valid_to is exclusive)? Anything not fully covered stays an exception."""
    aliases: dict[str, tuple[date, date | None]] = {}
    for p in proposals:
        for a in p["actions"]:
            if a["table"] == "instrument_alias" and a["operation"] == "INSERT":
                v = a["values"]
                aliases[v["source_symbol"]] = (v["valid_from"], v["valid_to"])
    out = []
    for ex in exceptions:
        if ex["kind"] != "MEMBER_WITHOUT_INSTRUMENT":
            continue
        ent = ex["entity"]
        spans = [(date.fromisoformat(i["start"]), date.fromisoformat(i["end_exclusive"]) if i["end_exclusive"] else anchor + timedelta(days=1))
                 for i in intervals if i["entity"] == ent]  # fmt: skip
        sym = ent.split(":", 1)[1]
        cover = aliases.get(sym)
        if cover is None:
            out.append(
                {
                    "entity": ent,
                    "result": "REMAINS",
                    "reason": "no instrument or alias proposed (non-tradable by design)",
                    "spans": spans,
                }
            )
            continue
        lo, hi = cover
        gaps = [(s, e) for s, e in spans if s < lo or (hi is not None and e > hi)]
        res = "REMAINS" if gaps else "CLEARED"
        out.append({"entity": ent, "result": res, "reason": f"proposed alias {lo}..{hi}" + (f" does not cover {gaps}" if gaps else " covers every member span"), "spans": spans})  # fmt: skip
    return out
