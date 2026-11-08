"""Frozen benchmark-release artifacts, read as the authority for benchmark eligibility and
findings. The API never recomputes eligibility: it serves what the audit wrote, with its release."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
