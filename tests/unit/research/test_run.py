"""The orchestrator only labels, gates and fingerprints; the engine does the work."""

from datetime import date
from decimal import Decimal as D

import pytest

from algo.backtest.costs.policy import PLACEHOLDER_COSTS
from algo.backtest.engine import BacktestConfig, RunResult
from algo.research.run import Purpose, execute, manifest


class FakeStrategy:
    id, version, params_hash = "s", "1", "abc"


def result(**kw):
    cfg = BacktestConfig(date(2025, 1, 1), date(2025, 2, 1), D(1000), cost=PLACEHOLDER_COSTS)
    r = RunResult("s", "1", "{}", "abc", "v", cfg)
    r.adjustment_versions = {2: "bb", 1: "aa"}
    r.__dict__.update(kw)
    return r


def test_manifest_is_deterministic_and_labelled():
    a = manifest(result(), Purpose.ENGINEERING_TEST_ONLY)
    b = manifest(result(), Purpose.ENGINEERING_TEST_ONLY)
    assert a == b and a["purpose"] == "ENGINEERING_TEST_ONLY"
    assert a["strategy"] == {"id": "s", "version": "1", "params_hash": "abc"}
    assert a["code_version"] == "v" and a["window"] == ["2025-01-01", "2025-02-01"]
    assert a["cost"]["placeholder"] is True and a["mode"] == "research"
    assert a["result_hash"] == result().result_hash


def test_dataset_fingerprint_ignores_dict_order_and_tracks_content():
    one = manifest(result(), Purpose.ENGINEERING_TEST_ONLY)["dataset_fingerprint"]
    swapped = result()
    swapped.adjustment_versions = {1: "aa", 2: "bb"}
    assert manifest(swapped, Purpose.ENGINEERING_TEST_ONLY)["dataset_fingerprint"] == one
    changed = result()
    changed.adjustment_versions = {1: "aa", 2: "XX"}
    assert manifest(changed, Purpose.ENGINEERING_TEST_ONLY)["dataset_fingerprint"] != one


def test_only_engineering_runs_are_possible_until_strict_readiness_and_registration_exist():
    for purpose in (Purpose.REGISTERED_EXPERIMENT, Purpose.EXPLORATORY_RESEARCH):
        with pytest.raises(NotImplementedError, match="readiness"):
            execute(None, FakeStrategy(), None, purpose=purpose)  # type: ignore[arg-type]
