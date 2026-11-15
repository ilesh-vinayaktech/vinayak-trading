# ruff: noqa: E501
"""docs/features.md, generated from the registry so it cannot disagree with the code (scripts/feature_docs.py writes or checks it)."""

from __future__ import annotations

from algo.features import registry

HISTORY = {
    "atr_14d": ["1 (2026-11-15): first version. Before first use the ATR was rescaled by raw_close/close on day t, because a split or bonus taking effect after t had changed it (found by the look-ahead harness); no earlier hash was ever registered."],
}  # fmt: skip
DEFAULT_HISTORY = "1 (2026-11-15): first version."
SECOND_SET = (
    "ret_1d",
    "rsi_14d",
    "dist_high_252d",
    "dist_low_252d",
    "volume_ratio_20_60d",
    "range_vol_20d",
    "max_drawdown_60d",
)  # added 2026-11-16 in algo.features.technical (ret_1d reuses price.ret)
HISTORY.update({n: ["1 (2026-11-16): first version."] for n in SECOND_SET})


def render() -> str:
    out = [
        "# Features (generated: do not edit; `uv run python scripts/feature_docs.py write`)",
        "",
        "Price and volume features only (Phase 1). A feature is identified by name and version; its `manifest_sha256` covers the manifest, the source of its module and of every",
        "declared helper, so a change to any of them needs a NEW version (`config/feature_manifests.json` and `store.register_all` refuse otherwise). A feature can be named in a",
        "study only when its status is USABLE, which `scripts/validate_features.py` sets after a stored, passed validation report.",
        "",
        "Common rules, stated in every manifest:",
        "",
    ]
    common = next(iter(registry.DEFINITIONS.values())).manifest
    for k in registry.COMMON:
        out.append(f"- **{k}**: {common[k]}")
    for name, d in registry.DEFINITIONS.items():
        m = d.manifest
        out += [
            "",
            f"## {name} (version {d.version})",
            "",
            f"- Definition: {m['definition']}",
            f"- Formula `{m['formula']}`, parameters {dict(m['parameters'])}, inputs {', '.join(m['inputs'])}, unit {m['unit']}",
            f"- Warm-up: {m['warmup_bars']} bars (no value before the instrument has them)",
            f"- Availability: {m['availability']}",
            f"- manifest_sha256: `{d.manifest_sha256}`",
            "- Version history:",
            *[f"  - {h}" for h in HISTORY.get(name, [DEFAULT_HISTORY])],
        ]
    return "\n".join(out) + "\n"
