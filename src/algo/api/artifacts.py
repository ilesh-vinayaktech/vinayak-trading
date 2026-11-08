"""Frozen benchmark-release artifacts, read as the authority for benchmark eligibility and
findings. The API never recomputes eligibility: it serves what the audit wrote, with its release."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# What each audit outcome code establishes. Existence, kind and hours are kept apart on purpose:
# an exchange file proves a session happened; it does not say what kind it was or when it ran.
OBSERVED: dict[str, tuple[str, str, str, str]] = {
    "CONFIRMED_REGULAR": (
        "exchange file exists; weekday session",
        "CONFIRMED",
        "REGULAR_BY_RULE",
        "ASSUMED_CURRENT_SCHEDULE",
    ),
    "CONFIRMED_SPECIAL": (
        "session existence confirmed by an exchange file; kind not confirmed",
        "CONFIRMED",
        "UNCONFIRMED",
        "UNKNOWN",
    ),
    "WEEKDAY_RULE_PROVISIONAL": (
        "weekday by calendar rule only; no exchange evidence",
        "PROVISIONAL",
        "REGULAR_BY_RULE",
        "ASSUMED_CURRENT_SCHEDULE",
    ),
    "BENCHMARK_ONLY_SESSION": (
        "listed session evidenced only by the benchmark itself",
        "UNCONFIRMED",
        "UNCONFIRMED",
        "UNKNOWN",
    ),
    "QUARANTINED_UNRESOLVED": (
        "exchange file quarantined; trading not independently shown",
        "UNCONFIRMED",
        "UNKNOWN",
        "UNKNOWN",
    ),
    "INVESTIGATE": ("value with no known session", "UNCONFIRMED", "UNKNOWN", "UNKNOWN"),
}
MISSING: dict[str, str] = {
    "DATA_GAP": "exchange file proves trading but the series has no value",
    "ALIGNMENT_GAP": "no value, but another series has one",
    "QUARANTINED_NO_VALUE": "no value; the exchange file is quarantined",
    "EXPECTED_CLOSED": "no value; holiday list or no file published",
    "EXPECTED_NO_SESSION": "no value on an ordinary weekend",
    "UNCONFIRMED_NO_VALUE": "weekday without a value and no closure evidence",
    "EXPECTED_CLOSED_INFERRED": "no value; exchange files either side chain over the day",
    "ARCHIVE_GAP_SESSION_LIKELY": "no value; exchange files imply a session",
}


def describe_outcomes(counts: dict[str, int]) -> list[dict[str, Any]]:
    """Counts of audit outcome codes as self-describing rows (existence / kind / hours apart)."""
    out: list[dict[str, Any]] = []
    for code, n in sorted(counts.items()):
        if code in OBSERVED:
            label, existence, kind, hours = OBSERVED[code]
            out.append(
                {
                    "code": code,
                    "count": n,
                    "label": label,
                    "existence": existence,
                    "kind": kind,
                    "hours": hours,
                }
            )
        else:
            label = MISSING.get(code, code.lower().replace("_", " "))
            out.append(
                {
                    "code": code,
                    "count": n,
                    "label": label,
                    "existence": None,
                    "kind": None,
                    "hours": None,
                }
            )
    return out


def session_properties(sessions_file: Path, release: dict[str, Any]) -> dict[str, Any] | None:
    """Existence, kind and hours of the LISTED special sessions, from the sessions file. Only used
    if that file is the one the release froze (same sha256); otherwise it describes other data."""
    if not sessions_file.exists():
        return None
    raw = sessions_file.read_bytes()
    frozen = release.get("calendar_inputs", {}).get("sessions_file_sha256")
    if hashlib.sha256(raw).hexdigest() != frozen:
        return None
    rows = json.loads(raw)["sessions"]

    def word(text: str) -> str:
        return text.split(" ", 1)[0]

    def tally(values: list[str]) -> dict[str, int]:
        return {k: values.count(k) for k in sorted(set(values))}

    hours = [word(r["hours_status"]) for r in rows]
    return {
        "listed_sessions": len(rows),
        "kind": tally([word(r["kind_status"]) for r in rows]),
        "opening_time": tally(hours),
        "closing_time": tally(hours),
    }


_RELEASE = re.compile(r"^benchmark-release-(\d+)\.(\d+)$")
_SERIES = re.compile(r"^B(\d+)_")


@dataclass(frozen=True)
class Artifacts:
    version: str
    release: dict[str, Any]
    eligibility: dict[str, Any]
    unresolved: dict[str, Any]
    alignment: dict[str, Any]
    session: dict[str, Any]

    def series_for(self, benchmark_id: int) -> str | None:
        for name in self.eligibility["benchmarks"]:
            m = _SERIES.match(name)
            if m and int(m.group(1)) == benchmark_id:
                return str(name)
        return None

    def eligibility_of(self, benchmark_id: int) -> dict[str, Any] | None:
        name = self.series_for(benchmark_id)
        return None if name is None else {"series": name, **self.eligibility["benchmarks"][name]}

    def session_dependencies(self, benchmark_id: int) -> dict[str, Any] | None:
        """Session-calendar outcomes for THIS series only (dates it has a value on, and the
        weekdays it lacks one), from the audit's per-date reconciliation."""
        name = self.series_for(benchmark_id)
        if name is None:
            return None
        short = name.split("_")[0]
        counts: dict[str, int] = {}
        for outcome, present in self.session["observed"].values():
            if short in present:
                counts[outcome] = counts.get(outcome, 0) + 1
        return {
            "series": name,
            "observed": describe_outcomes(counts),
            "missing": describe_outcomes(self.session["missing_counts"].get(name, {})),
        }

    def findings_for(self, benchmark_id: int) -> list[dict[str, Any]]:
        name = self.series_for(benchmark_id)
        if name is None:
            return []
        short = name.split("_")[0]
        return [
            f
            for f in self.unresolved["findings"]
            if "ALL" in f["applies_to"] or short in f["applies_to"]
        ]


def latest_release_dir(docs: Path) -> Path | None:
    found = []
    for p in docs.glob("benchmark-release-*"):
        m = _RELEASE.match(p.name)
        if m and (p / "release.json").exists():
            found.append(((int(m.group(1)), int(m.group(2))), p))
    return max(found)[1] if found else None


def audit_dir_for(docs: Path, version: str) -> Path:
    return docs / ("benchmark-audit" if version == "1.0" else f"benchmark-audit-{version}")


def load(docs: Path) -> Artifacts | None:
    rel_dir = latest_release_dir(docs)
    if rel_dir is None:
        return None
    release = json.loads((rel_dir / "release.json").read_text())
    audit = audit_dir_for(docs, release["release"])

    def read(name: str) -> dict[str, Any]:
        doc: dict[str, Any] = json.loads((audit / name).read_text())
        return doc

    return Artifacts(
        release["release"],
        release,
        read("benchmark_eligibility.json"),
        read("benchmark_unresolved_findings.json"),
        read("benchmark_alignment_report.json"),
        read("session_reconciliation_report.json"),
    )
