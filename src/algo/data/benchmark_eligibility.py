"""What a stored benchmark may be used for. Three separate states, never interchangeable:

  DATA_INGESTED            captured and stored
  RESEARCH_ELIGIBLE        meets the requirements of one named research use (daily or intraday)
  BENCHMARK_GATE_ELIGIBLE  meets the stricter requirements of automated strategy validation

Eligibility is decided per benchmark and per use from its CURRENT validation and from the unresolved
findings that apply to it. A finding blocks the uses it names; any unresolved finding blocks the
gate. Nothing here changes data or enables a gate: it reports what the evidence supports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from algo.data.benchmark_validate import REPORT_VERSION

DAILY, INTRADAY, GATE = "DAILY_RESEARCH", "INTRADAY_RESEARCH", "BENCHMARK_GATE"
USES = (DAILY, INTRADAY, GATE)
OPEN_STATUSES = ("UNRESOLVED",)  # ACCEPTED_WITH_EVIDENCE findings stay visible but do not block


def applicable(findings: Sequence[Mapping[str, Any]], benchmark: str) -> list[Mapping[str, Any]]:
    return [f for f in findings if "ALL" in f["applies_to"] or benchmark in f["applies_to"]]


def assess(
    benchmark: str, validation: Mapping[str, Any], findings: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """`validation`: covers_current_dataset, report_version, technical_validation_passed,
    check_states, factsheet_all_passed. `findings`: id, status, applies_to, blocks."""
    mine = applicable(findings, benchmark)
    open_ = [f for f in mine if f["status"] in OPEN_STATUSES]
    states = validation["check_states"] or {}
    stale = []
    if not validation["covers_current_dataset"]:
        stale.append("the latest validation does not cover the current dataset hash")
    if validation["report_version"] != REPORT_VERSION:
        stale.append(f"validation report version {validation['report_version']!r} is not current")
    if not validation["factsheet_all_passed"]:
        stale.append("factsheet reconciliation did not pass")
    if "FAIL" in states.values():
        stale.append("a check failed without an accepted or unresolved finding")
    daily = [*stale, *(f"{f['id']}: {f['title']}" for f in open_ if DAILY in f["blocks"])]
    intraday = [*daily, *(f"{f['id']}: {f['title']}" for f in open_ if INTRADAY in f["blocks"])]
    gate = [*stale]
    if not validation["technical_validation_passed"]:
        gate.append("technical validation did not pass (an accepted exception is not a pass)")
    gate += [f"{f['id']}: {f['title']}" for f in open_]
    use = {
        DAILY: {"eligible": not daily, "blockers": daily},
        INTRADAY: {"eligible": not intraday, "blockers": intraday},
        GATE: {"eligible": not gate, "blockers": gate},
    }
    state = (
        "BENCHMARK_GATE_ELIGIBLE" if use[GATE]["eligible"]
        else "RESEARCH_ELIGIBLE" if use[DAILY]["eligible"] else "DATA_INGESTED"
    )  # fmt: skip
    disclosed = {k: v for k, v in states.items() if v not in ("PASS",)}
    return {"state": state, "uses": use, "disclosed_check_findings": disclosed,
            "applicable_findings": [f["id"] for f in mine]}  # fmt: skip
