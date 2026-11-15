# ruff: noqa: E501
import dataclasses
import json
from datetime import date, timedelta
from pathlib import Path

from algo.features import fundamental, registry

ROOT = Path(__file__).resolve().parents[3]


def test_there_are_thirty_five_features_in_three_families_each_with_a_manifest_that_states_its_rules():
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
            "ret_1d",
            "rsi_14d",
            "dist_high_252d",
            "dist_low_252d",
            "volume_ratio_20_60d",
            "range_vol_20d",
            "max_drawdown_60d",
            *[f"fund_{k}" for k in fundamental.KEYS],
        ]
    )
    for f in d.values():
        assert (
            f.version == "1"
            and f.family in ("price", "technical", "fundamental")
            and f.manifest["family"] == f.family
        )
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


def test_a_fundamental_feature_declares_the_ratio_engine_as_a_dependency_and_only_it_reads_filings():
    f = registry.DEFINITIONS["fund_roe"]
    assert (
        f.needs_filings
        and f.family == "fundamental"
        and f.manifest["inputs"] == ["filings"]
        and f.manifest["parameters"] == {"ratio": "roe"}
    )
    assert (
        "algo.data.ratios" in f.extra_helpers
        and not registry.DEFINITIONS["ret_5d"].extra_helpers
        and not registry.DEFINITIONS["rsi_14d"].needs_filings
    )
    base = f.manifest_sha256
    assert (
        dataclasses.replace(f, extra_helpers={}).manifest_sha256 != base
    )  # without the declared engine the hash differs


def test_a_price_feature_with_no_filings_still_computes_and_a_fundamental_one_without_filings_has_no_values():
    from datetime import UTC, date, datetime, timedelta
    from decimal import Decimal as D

    from algo.features._shared import SessionBar

    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(10)]
    bars = {
        d: SessionBar(
            d, D(11), D(9), D(10), D(10), D(100), datetime(d.year, d.month, d.day, 13, tzinfo=UTC)
        )
        for d in days
    }
    assert registry.DEFINITIONS["ret_1d"].calc(days, bars)  # no filings argument needed
    assert (
        registry.DEFINITIONS["fund_roe"].calc(days, bars) == {}
    )  # none given: an empty history, no value, no error
