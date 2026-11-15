# ruff: noqa: E501
"""Three separate scorecards, never blended: platform correctness, strategy validity, operational reliability.

A platform can be correct while no strategy is valid, and reliable while computing wrong numbers, so each question gets its own card.
An item is PASS, WARN, FAIL or UNKNOWN (no evidence yet). A card is FAIL if any item failed; else ATTENTION if any warns; else INCOMPLETE if any item has
no evidence (missing evidence is never reported as OK); else OK. Pure: it is given the signals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _item(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _status(items: Sequence[dict[str, str]]) -> str:
    states = {i["status"] for i in items}
    if "FAIL" in states:
        return "FAIL"
    if "WARN" in states:
        return "ATTENTION"
    if "UNKNOWN" in states:
        return "INCOMPLETE"
    return "OK"


def _check(label: str, name: str, result: str | None) -> dict[str, str]:
    if result is None:
        return _item(label, "UNKNOWN", f"the {name} check has never run")
    return _item(
        label,
        result,
        f"the newest {name} run {'found nothing' if result == 'PASS' else 'found a problem'}",
    )


def build(
    *,
    dq: Mapping[str, str | None],
    latest_run: Mapping[str, Any] | None,
    quarantined: Sequence[str],
    validation: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    heartbeat_problems: Sequence[str],
    kite_state: str | None,
) -> dict[str, dict[str, Any]]:
    # ---- platform correctness: is what the platform computes and stores right?
    p = [
        _check("bar completeness", "completeness", dq.get("completeness")),
        _check("price continuity", "continuity", dq.get("continuity")),
    ]
    p.append(
        _item(
            "quarantined loads",
            "FAIL",
            f"{len(quarantined)} partition(s) refused: {', '.join(quarantined)}",
        )
        if quarantined
        else _item("quarantined loads", "PASS", "none")
    )
    if latest_run is None:
        p.append(_item("ledger reconciliation", "UNKNOWN", "no backtest has produced a ledger yet"))
    elif latest_run.get("accounting_complete") and latest_run.get("ledger_reconciled"):
        p.append(_item("ledger reconciliation", "PASS", "the newest backtest's ledger reconciles"))
    else:
        p.append(
            _item(
                "ledger reconciliation",
                "FAIL",
                "the newest backtest's ledger does not reconcile or its accounting is incomplete",
            )
        )
    # ---- strategy validity: is there evidence that any strategy works?
    reports, passed = int(validation["reports"]), int(validation["passed"])
    if reports == 0:
        v = [_item("development evidence", "UNKNOWN", "no validation report exists yet")]
    elif passed == 0:
        v = [
            _item(
                "development evidence",
                "WARN",
                f"{reports} report(s) exist but no development report has passed: nothing is promotable",
            )
        ]
    else:
        v = [
            _item(
                "development evidence",
                "PASS",
                f"{passed} of {reports} development report(s) passed",
            )
        ]
    if validation.get("holdout_consumed"):
        v.append(_item("holdout", "PASS", "the one holdout evaluation has been run"))
    else:
        v.append(
            _item(
                "holdout",
                "UNKNOWN",
                "the holdout has not been evaluated: no result is proven out of sample",
            )
        )
    # ---- operational reliability: does it keep running?
    ran = [j for j in jobs if j.get("last_run")]
    failed = [j for j in ran if j["last_run"].get("status") != "ok"]
    never = len(jobs) - len(ran)
    if not ran:
        o = [_item("scheduled jobs", "UNKNOWN", f"none of the {len(jobs)} jobs has run yet")]
    elif failed:
        o = [
            _item(
                "scheduled jobs",
                "FAIL",
                f"{len(failed)} job(s) failed on their last run: {', '.join(j['name'] for j in failed[:5])}",
            )
        ]
    else:
        o = [
            _item(
                "scheduled jobs",
                "PASS",
                f"all {len(ran)} job(s) that have run ended well"
                + (f"; {never} never ran" if never else ""),
            )
        ]
    o.append(
        _item("running processes", "FAIL", "; ".join(heartbeat_problems))
        if heartbeat_problems
        else _item("running processes", "PASS", "no expected process is silent")
    )
    o.append(
        _item("Kite session", "PASS", "connected")
        if kite_state == "connected"
        else _item("Kite session", "WARN", f"the Kite session is {kite_state or 'not connected'}")
    )
    return {
        "platform_correctness": {"status": _status(p), "items": p},
        "strategy_validity": {"status": _status(v), "items": v},
        "operational_reliability": {"status": _status(o), "items": o},
    }
