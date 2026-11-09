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

# Corporate-action successors stated in the recorded decision notes (symbol -> (successor, effective, basis)).
SUCCESSORS: dict[str, tuple[str, str, str]] = {
    "ABIRLANUVO": (
        "GRASIM",
        "2017-07-01",
        "amalgamation into Grasim (decision note; not an alias to ABCAPITAL)",
    ),
    "BHARATFIN": (
        "INDUSINDBK",
        "2019-07-04",
        "amalgamation into IndusInd Bank (effective date from the bank's announcement)",
    ),
    "DALMIABHA": (
        "DALBHARAT",
        "2019-01-09",
        "scheme of arrangement; shares of Odisha Cement (renamed Dalmia Bharat 2019-04-15) allotted",
    ),
    "PEL": ("PIRAMALFIN", "2025-09-16", "merger into Piramal Finance Ltd (filing of 2025-09-16)"),
    "GSPL": (
        "GUJENERGY",
        "2026-05-01",
        "amalgamation into Gujarat Gas, now Gujarat Energy (scheme effective 2026-05-01)",
    ),
    "MINDTREE": ("LTIM", "2022-11-14", "amalgamation into L&T Infotech, now LTIMindtree"),
}
SAME_ISSUER_NEW_INSTRUMENT = {
    "HEXAWARE": ("HEXT", "2025-02-19", "same issuer relisted by IPO as a new security")
}

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
         evidence: Sequence[str], caveats: Sequence[str] = ()) -> dict[str, Any]:  # fmt: skip
    return {
        "item_id": item_id, "decision_id": rec["decision_id"], "decision": rec["decision"],
        "reviewer": rec["reviewer"], "status": "PROPOSED", "kind": kind, "summary": summary,
        "actions": actions, "evidence": [rec["evidence_ref"], *evidence], "caveats": list(caveats),
    }  # fmt: skip


def symbol_proposal(
    symbol: str, rec: Mapping[str, Any], facts: Mapping[str, Any], existing: Mapping[str, Any]
) -> dict[str, Any]:  # fmt: skip
    """`existing` = {"instrument": {...}|None, "aliases": [(valid_from, valid_to), ...]}."""
    item_id, decision = f"symbol:{symbol}", rec["decision"]
    first, last, isin = facts["first"], facts["last"], facts["isin"]
    inst, aliases = existing["instrument"], existing["aliases"]
    end = (
        last + timedelta(days=1) if last else None
    )  # first day it no longer trades (end exclusive)
    if decision == "KEEP_PLACEHOLDER":
        return _one(item_id, rec, "PLACEHOLDER", f"{symbol} is a non-tradable index placeholder: no instrument, no alias, no ISIN",
                    [], ["membership: reviewed placeholder replacement record"])  # fmt: skip
    caveats: list[str] = []
    actions: list[dict[str, Any]] = []
    if decision == "CONFIRM_MAPPING":
        start = rec["effective_date"]
        if any(a[0] == start for a in aliases):
            return _one(item_id, rec, "ALIAS_ALREADY_PRESENT", f"alias {symbol} -> instrument {inst['id']} valid from {start} is already in the master", [], [])  # fmt: skip
        actions.append({"table": "instrument_alias", "operation": "INSERT", "values": {"instrument_id": inst["id"], "source": "nse", "source_symbol": symbol, "valid_from": start, "valid_to": end}})  # fmt: skip
        return _one(
            item_id,
            rec,
            "SYMBOL_ALIAS",
            f"map {symbol} to instrument {inst['id']} from {start}",
            actions,
            [],
        )
    if decision == "SET_EFFECTIVE_DATE":
        change = rec["effective_date"]
        actions = [
            {"table": "instrument", "operation": "INSERT", "values": {"symbol": symbol, "isin": isin, "status": "delisted", "listed_on": first, "delisted_on": change, "note": "old-ISIN identity of the same issuer"}},
            {"table": "instrument_alias", "operation": "INSERT", "values": {"instrument_id": "<new>", "source": "nse", "source_symbol": symbol, "valid_from": first, "valid_to": change}},
            {"table": "(no table yet) continuity", "operation": "RECORD", "values": {"kind": "SAME_ISSUER_ISIN_CHANGE", "old_isin": isin, "new_instrument_id": inst["id"], "effective": change, "cause": "10:1 face-value split"}},
        ]  # fmt: skip
        if any(a[0] < change for a in aliases):
            caveats.append(f"instrument {inst['id']} already has an alias for {symbol} starting before {change}: resolve the overlap (its bars before {change} traded under the old ISIN)")  # fmt: skip
        return _one(item_id, rec, "SAME_ISSUER_ISIN_CHANGE", f"keep two ISIN identities for {symbol}, linked by the split on {change}", actions, [], caveats)  # fmt: skip
    # KEEP_SEPARATE / NO_SUCCESSOR: the security stays its own historical instrument
    if inst is None:
        actions.append({"table": "instrument", "operation": "INSERT", "values": {"symbol": symbol, "isin": isin, "status": "delisted", "listed_on": first, "delisted_on": end}})  # fmt: skip
        actions.append({"table": "instrument_alias", "operation": "INSERT", "values": {"instrument_id": "<new>", "source": "nse", "source_symbol": symbol, "valid_from": first, "valid_to": end}})  # fmt: skip
    else:
        if inst["isin"] is None and isin:
            actions.append({"table": "instrument", "operation": "UPDATE", "values": {"instrument_id": inst["id"], "isin": isin}})  # fmt: skip
        if not aliases:
            actions.append({"table": "instrument_alias", "operation": "INSERT", "values": {"instrument_id": inst["id"], "source": "nse", "source_symbol": symbol, "valid_from": first, "valid_to": end}})  # fmt: skip
    if symbol in SUCCESSORS:
        succ, eff, basis = SUCCESSORS[symbol]
        actions.append({"table": "(no table yet) successor", "operation": "RECORD", "values": {"kind": "AMALGAMATED_INTO", "successor_symbol": succ, "effective": eff, "basis": basis, "alias": False}})  # fmt: skip
    if symbol in SAME_ISSUER_NEW_INSTRUMENT:
        succ, eff, basis = SAME_ISSUER_NEW_INSTRUMENT[symbol]
        actions.append({"table": "(no table yet) continuity", "operation": "RECORD", "values": {"kind": "SAME_ISSUER_NEW_INSTRUMENT", "successor_symbol": succ, "effective": eff, "basis": basis, "alias": False}})  # fmt: skip
    if not actions:
        return _one(
            item_id, rec, "NO_CHANGE_NEEDED", f"{symbol} is already complete in the master", [], []
        )
    kind = "HISTORICAL_INSTRUMENT" if inst is None else "COMPLETE_EXISTING_INSTRUMENT"
    return _one(item_id, rec, kind, f"{symbol} stays its own historical instrument; successor is a corporate-action fact, not an alias", actions, [], caveats)  # fmt: skip


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
