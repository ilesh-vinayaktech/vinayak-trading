# ruff: noqa: E501
"""The feature definitions of Phase 1 (docs/vti-phase1-spec.md, item C): price and volume only, version 1. Each carries a manifest (canonical JSON) and a
`manifest_sha256` that covers the manifest, the source of the module that implements it and the source of every helper it declares as a dependency:
editing any of them without a new version changes the hash, which the version guard (`store.register_all`) and a committed golden file both catch."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from algo.data import ratios as ratio_engine
from algo.features import _shared, fundamental, price, technical
from algo.features._shared import Result, SessionBar

VERSION = "1"
Compute = Callable[
    ..., Result
]  # (sessions, bars) for price features; (sessions, bars, FilingsHistory) when `needs_filings`

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
    needs_filings: bool = (
        False  # a fundamental feature: it also reads the company's filings (FilingsHistory)
    )
    extra_helpers: Mapping[str, Any] = field(
        default_factory=dict
    )  # modules, beyond the shared ones, whose source the value depends on (their source joins the hash)

    def calc(
        self,
        sessions: Sequence[date],
        bars: Mapping[date, SessionBar],
        filings: fundamental.FilingsHistory | None = None,
    ) -> Result:
        """Compute for one company: the price features need only the bars; a fundamental feature also its filings (none = no filings, so no values)."""
        if self.needs_filings:
            return self.compute(sessions, bars, filings or fundamental.FilingsHistory({}))
        return self.compute(sessions, bars)

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
                for n, m in sorted({**HELPERS, **self.extra_helpers}.items())
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
    *,
    module: Any = price,
    family: str = "price",
) -> FeatureDef:
    manifest = {
        "name": name,
        "version": VERSION,
        "family": family,
        "formula": formula,
        "parameters": params,
        "inputs": inputs,
        "window": warmup,
        "warmup_bars": warmup,
        "unit": unit,
        "definition": text,
        **COMMON,
    }
    return FeatureDef(name, VERSION, family, manifest, module, fn)


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
    out["ret_1d"] = _def(
        "ret_1d",
        "ret",
        {"n": 1},
        2,
        "fraction",
        ["close"],
        price.ret(1),
        "close[t] / close[t-n] - 1",
    )
    tech: dict[str, Any] = {"module": technical, "family": "technical"}
    out["rsi_14d"] = _def(
        "rsi_14d", "rsi", {"n": 14}, 15, "index (0 to 100)", ["close"], technical.rsi(14),
        "Wilder RSI: the first value uses the mean of the first 14 gains and 14 losses, then avg[t] = (avg[t-1] * 13 + change[t]) / 14 for each; 100 - 100 / (1 + avg gain / avg loss); only rises give 100, no movement gives 50; a gap restarts the chain",
        **tech,
    )  # fmt: skip
    out["dist_high_252d"] = _def(
        "dist_high_252d",
        "dist_high",
        {"n": 252},
        252,
        "fraction",
        ["close"],
        technical.dist_high(252),
        "close[t] / max(close[t-n+1..t]) - 1, never positive",
        **tech,
    )
    out["dist_low_252d"] = _def(
        "dist_low_252d",
        "dist_low",
        {"n": 252},
        252,
        "fraction",
        ["close"],
        technical.dist_low(252),
        "close[t] / min(close[t-n+1..t]) - 1, never negative",
        **tech,
    )
    out["volume_ratio_20_60d"] = _def(
        "volume_ratio_20_60d", "volume_ratio", {"short": 20, "long": 60}, 60, "ratio", ["raw_volume"], technical.volume_ratio(20, 60),
        "mean raw volume of the last 20 sessions over the mean raw volume of the last 60; no value when the last 60 sessions traded nothing", **tech,
    )  # fmt: skip
    out["range_vol_20d"] = _def(
        "range_vol_20d", "range_vol", {"n": 20}, 20, "fraction", ["high", "low"], technical.range_vol(20),
        "Parkinson range volatility: sqrt(mean(ln(high/low)^2 over the last 20 sessions) / (4 ln 2)), per day, not annualised; no value if any session has a non-positive low or a high below its low", **tech,
    )  # fmt: skip
    out["max_drawdown_60d"] = _def(
        "max_drawdown_60d", "max_drawdown", {"n": 60}, 60, "fraction", ["close"], technical.max_drawdown(60),
        "the deepest fall from a running peak among the last 60 closes: min over the window of close / running-high - 1, zero or negative", **tech,
    )  # fmt: skip
    out.update(_fundamental_defs())
    return out


def _fundamental_defs() -> dict[str, FeatureDef]:
    """One feature per price-free ratio of the Screener's engine (fundamental.KEYS), named fund_<ratio>."""
    defs = {d.key: d for d in ratio_engine.RATIOS}
    out: dict[str, FeatureDef] = {}
    overrides = {
        "adjustment": "none: a ratio of filed results, no price is used",
        "missing_data": "a ratio the filings cannot give (a loss a year ago, no balance sheet yet, no filing yet) gives no value; nothing is imputed or carried across a restatement; the value holds from one filing to the next",
        "availability": "the filing time of the filing that produced the value; a filing counts from the session after the day it was filed, never the same day",
    }
    for key in fundamental.KEYS:
        r = defs[key]
        name = f"fund_{key}"
        manifest = {
            "name": name, "version": VERSION, "family": "fundamental", "formula": "fundamental_ratio", "parameters": {"ratio": key},
            "inputs": ["filings"], "window": 0, "warmup_bars": 0, "unit": r.unit,
            "definition": f"{r.label}: {r.formula}", **{**COMMON, **overrides},
        }  # fmt: skip
        out[name] = FeatureDef(
            name, VERSION, "fundamental", manifest, fundamental, fundamental.ratio(key),
            needs_filings=True, extra_helpers={"algo.data.ratios": ratio_engine},
        )  # fmt: skip
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
