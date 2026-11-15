# ruff: noqa: E501
"""The feature definitions of Phase 1 (docs/vti-phase1-spec.md, item C): price and volume only, version 1. Each carries a manifest (canonical JSON) and a
`manifest_sha256` that covers the manifest, the source of the module that implements it and the source of every helper it declares as a dependency:
editing any of them without a new version changes the hash, which the version guard (`store.register_all`) and a committed golden file both catch."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from algo.features import _shared, price
from algo.features._shared import Result, SessionBar

VERSION = "1"
Compute = Callable[[Sequence[date], Mapping[date, SessionBar]], Result]

COMMON: dict[str, Any] = {
    "adjustment": "split and bonus adjusted, point in time as of the feature day (BarReader mode 'split'); traded value uses raw close and raw volume",
    "missing_data": "a window containing a session with no bar gives no value; nothing is interpolated or filled; a value inside its warm-up is absent, never zero",
    "availability": "the latest availability of every input bar (BarReader visible_after plus its publish lag); never served earlier",
    "session_rule": "a session is a day on which at least half of the dataset's instruments have a bar",
    "precision": "values are quantised to 12 decimal places (half-even)",
}
HELPERS = {"algo.features._shared": _shared}


@dataclass(frozen=True)
class FeatureDef:
    name: str
    version: str
    family: str
    manifest: Mapping[str, Any]
    module: Any  # the module whose source is part of the hash
    compute: Compute

    @property
    def manifest_sha256(self) -> str:
        doc = {
            "manifest": self.manifest,
            "module": {
                self.module.__name__: hashlib.sha256(
                    inspect.getsource(self.module).encode()
                ).hexdigest()
            },
            "helpers": {
                n: hashlib.sha256(inspect.getsource(m).encode()).hexdigest()
                for n, m in sorted(HELPERS.items())
            },
        }
        return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def _def(
    name: str,
    formula: str,
    params: dict[str, int],
    warmup: int,
    unit: str,
    inputs: list[str],
    fn: Compute,
    text: str,
) -> FeatureDef:
    manifest = {
        "name": name,
        "version": VERSION,
        "family": "price",
        "formula": formula,
        "parameters": params,
        "inputs": inputs,
        "window": warmup,
        "warmup_bars": warmup,
        "unit": unit,
        "definition": text,
        **COMMON,
    }
    return FeatureDef(name, VERSION, "price", manifest, price, fn)


def _build() -> dict[str, FeatureDef]:
    out: dict[str, FeatureDef] = {}
    for n in (5, 20, 60, 120, 252):
        out[f"ret_{n}d"] = _def(
            f"ret_{n}d",
            "ret",
            {"n": n},
            n + 1,
            "fraction",
            ["close"],
            price.ret(n),
            "close[t] / close[t-n] - 1",
        )
    for n in (20, 60):
        out[f"vol_{n}d"] = _def(
            f"vol_{n}d",
            "vol",
            {"n": n},
            n + 1,
            "fraction",
            ["close"],
            price.vol(n),
            "sample standard deviation (ddof = 1) of the last n daily simple returns, not annualised",
        )
    out["atr_14d"] = _def(
        "atr_14d",
        "atr",
        {"n": 14},
        15,
        "price",
        ["high", "low", "close", "raw_close"],
        price.atr(14),
        "Wilder ATR: first value is the mean of the first 14 true ranges, then ATR[t] = (ATR[t-1] * 13 + TR[t]) / 14; a gap restarts the chain; in price units as of t: multiplied by raw_close[t] / close[t] so a later split or bonus does not change it",
    )
    out["atr_pct_14d"] = _def(
        "atr_pct_14d",
        "atr_pct",
        {"n": 14},
        15,
        "fraction",
        ["high", "low", "close"],
        price.atr_pct(14),
        "atr_14d / close[t]",
    )
    for n in (50, 200):
        out[f"dist_sma_{n}d"] = _def(
            f"dist_sma_{n}d",
            "dist_sma",
            {"n": n},
            n,
            "fraction",
            ["close"],
            price.dist_sma(n),
            "close[t] / mean(close[t-n+1..t]) - 1",
        )
    out["traded_value_20d"] = _def(
        "traded_value_20d",
        "traded_value",
        {"n": 20},
        20,
        "rupees",
        ["raw_close", "raw_volume"],
        price.traded_value(20),
        "mean over the last 20 sessions of raw close times raw volume",
    )
    return out


DEFINITIONS: dict[str, FeatureDef] = _build()


def golden() -> dict[str, str]:
    """name@version -> manifest_sha256, the value committed in config/feature_manifests.json."""
    return {f"{d.name}@{d.version}": d.manifest_sha256 for d in DEFINITIONS.values()}


def sessions_from(
    bars_by_instrument: Mapping[int, Mapping[date, Any]], share: float = 0.5
) -> list[date]:
    """The market sessions of a dataset: every day on which at least `share` of the instruments have a bar."""
    n = len(bars_by_instrument)
    counts: dict[date, int] = {}
    for bars in bars_by_instrument.values():
        for d in bars:
            counts[d] = counts.get(d, 0) + 1
    return sorted(d for d, c in counts.items() if n and c / n >= share)
