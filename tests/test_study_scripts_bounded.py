"""Every research study's bar query must have an upper date bound, so it cannot read the protected holdout (config/research_holdout.json).

KNOWN_UNBOUNDED are the older studies found unbounded on 2026-11-19 (their 2024+/2025+ results are contaminated); the list may only shrink."""

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
KNOWN_UNBOUNDED = {
    "study_accuracy_ceiling.py", "study_candle_patterns.py", "study_conditions.py", "study_confluence.py", "study_horizon_thresholds.py", "study_hypotheses.py",
    "study_inside_bar.py", "study_learned_signals.py", "study_own_direction.py", "study_trend_rule.py", "study_winners_first.py",
}  # fmt: skip


def _unbounded(path: Path) -> bool:
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if (
            ("FROM bar_1d" in line or "FROM {BARS}" in line)
            and not re.search(r"(ts|date)\s*<", " ".join(lines[i : i + 2]))
        ):  # {BARS} is study_common's Kite source: a study that reads it is checked like one that reads bar_1d
            return True
    return False


def test_new_study_scripts_bound_their_bar_queries():
    bad = {
        p.name for p in SCRIPTS.glob("study_*.py") if p.name != "study_common.py" and _unbounded(p)
    }  # study_common only DEFINES the shared source; each study that reads it adds its own bound
    assert bad - KNOWN_UNBOUNDED == set()
    assert KNOWN_UNBOUNDED - bad == set(), "now bounded: remove it from KNOWN_UNBOUNDED"


def test_the_check_catches_an_unbounded_query(tmp_path):
    p = tmp_path / "study_x.py"
    p.write_text("q = \"SELECT * FROM bar_1d WHERE ts >= '2019-01-01'\"\n")
    assert _unbounded(p)
    p.write_text("q = \"SELECT * FROM bar_1d WHERE ts >= '2019-01-01' AND ts < %s\"\n")
    assert not _unbounded(p)


def test_the_check_also_covers_the_shared_kite_source(tmp_path):
    p = tmp_path / "study_y.py"
    p.write_text("q = f\" FROM {BARS} WHERE source='kite' AND ts >= '2019-01-01'\"\n")
    assert _unbounded(p)
    p.write_text(
        "q = f\" FROM {BARS} WHERE source='kite' AND ts >= '2019-01-01' AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= %s\"\n"
    )
    assert not _unbounded(p)
