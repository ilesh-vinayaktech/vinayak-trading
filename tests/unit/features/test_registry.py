# ruff: noqa: E501
import dataclasses
import json
from datetime import date, timedelta
from pathlib import Path

from algo.features import registry

ROOT = Path(__file__).resolve().parents[3]


def test_there_are_twelve_price_features_each_with_a_manifest_that_states_its_rules():
    d = registry.DEFINITIONS
    assert sorted(d) == sorted(
        [
            "ret_5d",
            "ret_20d",
            "ret_60d",
            "ret_120d",
            "ret_252d",
            "vol_20d",
            "vol_60d",
            "atr_14d",
            "atr_pct_14d",
            "dist_sma_50d",
            "dist_sma_200d",
            "traded_value_20d",
        ]
    )
    for f in d.values():
        assert f.version == "1" and f.family == "price" and f.manifest["family"] == "price"
        for key in (
            "formula",
            "parameters",
            "inputs",
            "window",
            "warmup_bars",
            "unit",
            "adjustment",
            "missing_data",
            "availability",
            "session_rule",
            "precision",
            "definition",
            "version",
        ):
            assert f.manifest[key] not in (None, ""), (f.name, key)
    assert (
        registry.DEFINITIONS["ret_252d"].manifest["warmup_bars"] == 253
        and registry.DEFINITIONS["dist_sma_200d"].manifest["warmup_bars"] == 200
    )


def test_the_committed_hashes_are_the_codes_hashes_so_an_edit_without_a_new_version_fails_here():
    stored = json.loads((ROOT / "config/feature_manifests.json").read_text())
    now = registry.golden()
    changed = sorted(k for k in now if k in stored and stored[k] != now[k])
    assert not changed, (
        f"{changed} changed without a new version. Add a NEW version (never edit v1); then run `uv run python scripts/feature_manifests.py write`."
    )
    assert set(stored) == set(now), (
        "a feature was added or removed: run `uv run python scripts/feature_manifests.py write` with the new version"
    )


def test_the_hash_covers_the_manifest_the_module_source_and_every_declared_helper(monkeypatch):
    f = registry.DEFINITIONS["ret_20d"]
    base = f.manifest_sha256
    assert (
        dataclasses.replace(f, manifest={**f.manifest, "formula": "other"}).manifest_sha256 != base
    )  # the manifest
    assert (
        dataclasses.replace(f, module=registry).manifest_sha256 != base
    )  # the module that implements it
    monkeypatch.setattr(
        registry, "HELPERS", {**registry.HELPERS, "algo.features.registry": registry}
    )
    assert f.manifest_sha256 != base  # a helper declared as a dependency


def test_a_session_is_a_day_on_which_at_least_half_the_instruments_have_a_bar():
    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(4)]
    bars = {
        1: dict.fromkeys(days[:3], 1),
        2: dict.fromkeys([days[0], days[1]], 1),
        3: {days[0]: 1},
        4: {days[1]: 1},
    }
    # day 0: 3 of 4; day 1: 4 of 4; day 2: 1 of 4; day 3: none
    assert registry.sessions_from(bars) == days[:2]
    assert registry.sessions_from(bars, share=0.25) == days[:3]
    assert registry.sessions_from({}) == []
