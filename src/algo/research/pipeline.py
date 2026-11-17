# ruff: noqa: E501
"""What to do next for one study on its way through the research pipeline: trials, then the development verdict, then (only if it passed) the inner holdout.

Pure: the caller (scripts/run_pipeline.py) reads the study's runs and the passed flag and queues what this says. The study workers do the actual work."""

from __future__ import annotations

TERMINAL = ("DONE", "FAILED", "CANCELLED")


def next_step(runs: dict[str, str], passed: bool | None) -> tuple[str | None, bool]:
    """(the kind of run to queue now or None, whether this study is finished). `runs` maps a run kind to the status of its newest run."""
    for kind in ("trials", "verdict"):
        status = runs.get(kind)
        if status is None:
            return kind, False
        if status not in TERMINAL:
            return None, False  # still queued or running: wait
        if status != "DONE":
            return None, True  # it ended without a result: nothing more can follow
    if not passed:
        return None, True  # failed development: the inner holdout is only for studies that passed
    status = runs.get("holdout")
    if status is None:
        return "holdout", False
    return None, status in TERMINAL
