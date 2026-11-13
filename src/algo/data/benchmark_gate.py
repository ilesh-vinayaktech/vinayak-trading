# ruff: noqa: E501
"""The benchmark gate: whether a study may use a benchmark for its benchmark gates. When the gate is on (config/benchmark_gate.json), the
benchmark must be BENCHMARK_GATE_ELIGIBLE in the latest frozen benchmark release; when it is off, a passing validation is enough."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def is_enabled(path: Path) -> bool:
    """Off when the file is missing; on only when it says `"enabled": true`."""
    return path.exists() and json.loads(path.read_text()).get("enabled") is True


def blocker(artifacts: Any, benchmark_id: int, enabled: bool) -> str | None:
    """None when the benchmark may be used; otherwise why not. `artifacts` is algo.api.artifacts.Artifacts, or None without a release."""
    if not enabled:
        return None
    if artifacts is None:
        return "the benchmark gate is on but no benchmark release exists"
    found = artifacts.eligibility_of(benchmark_id)
    if found is None:
        return f"benchmark {benchmark_id} is not in benchmark release {artifacts.version}"
    use = found["uses"]["BENCHMARK_GATE"]
    if use["eligible"]:
        return None
    why = "; ".join(use["blockers"]) or "no reason recorded"
    return f"{found['series']} is not BENCHMARK_GATE_ELIGIBLE in release {artifacts.version}: {why}"
