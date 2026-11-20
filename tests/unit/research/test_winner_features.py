"""Feature engineering V2 for the early-large-upside research: every feature is known at the close of its own session (no look-ahead), documented, and deterministic."""

from typing import Any

import numpy as np
import pandas as pd

from algo.research.winner_features import GROUPS, META, compute_features

Arr = np.ndarray[Any, Any]


def panel(t: int = 320, s: int = 5, seed: int = 1) -> dict[str, Arr]:
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0.0003, 0.02, (t, s)), axis=0)
    o = c * (1 + rng.normal(0, 0.004, (t, s)))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, (t, s))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, (t, s))))
    v = rng.integers(10_000, 100_000, (t, s)).astype(float)
    dq = v * rng.uniform(0.2, 0.8, (t, s))
    return {"o": o, "h": h, "lo": lo, "c": c, "v": v, "dq": dq}


def feats(p: dict[str, Arr], groups: tuple[str, ...] | None = None) -> dict[str, Arr]:
    return {
        m.name: a
        for m, a in compute_features(p["o"], p["h"], p["lo"], p["c"], p["v"], p["dq"], groups)
    }


def test_every_feature_is_documented_and_groups_are_the_spec_ones() -> None:
    f = feats(panel())
    assert set(f) == set(META)
    assert {m.group for m in META.values()} == set(GROUPS)
    for m in META.values():
        assert m.description and m.lookback >= 1 and m.source and m.missing


def test_v1_group_has_the_24_features_of_the_v1_model() -> None:
    v1 = [n for n, m in META.items() if m.group == "v1"]
    assert len(v1) == 24
    assert {"r1", "r5", "r20", "r60", "vol60", "bwr", "rng15", "lturn", "breadth50"} <= set(v1)


def test_volatility_flag_marks_group_c_and_the_v1_volatility_features() -> None:
    flagged = {n for n, m in META.items() if m.volatility}
    assert {"vol60", "bwr", "rng15"} <= flagged
    assert all(m.volatility for m in META.values() if m.group == "volatility")
    assert not any(m.volatility for m in META.values() if m.group in ("price", "volume", "early"))


def test_changing_any_future_data_never_changes_a_past_feature() -> None:
    p = panel()
    base = feats(p)
    cut = 250
    q = {k: v.copy() for k, v in p.items()}
    rng = np.random.default_rng(9)
    for k in q:
        q[k][cut + 1 :] = q[k][cut + 1 :] * rng.uniform(
            0.2, 5.0, q[k][cut + 1 :].shape
        )  # wreck everything after the cut
    q["h"] = np.maximum(q["h"], np.maximum(q["o"], q["c"]))
    after = feats(q)
    for name in base:
        assert np.array_equal(base[name][: cut + 1], after[name][: cut + 1], equal_nan=True), name


def test_deterministic() -> None:
    p = panel()
    a, b = feats(p), feats(p)
    for n in a:
        assert np.array_equal(a[n], b[n], equal_nan=True), n


def test_returns_and_delivery_and_range_position_hand_values() -> None:
    p = panel()
    f = feats(p)
    c, v, dq, h, lo = p["c"], p["v"], p["dq"], p["h"], p["lo"]
    assert np.isclose(f["ret_5d"][100, 2], c[100, 2] / c[95, 2] - 1)
    assert np.isclose(f["delivery_pct"][100, 2], dq[100, 2] / v[100, 2] * 100)
    assert np.isclose(
        f["close_range_position"][100, 2], (c[100, 2] - lo[100, 2]) / (h[100, 2] - lo[100, 2])
    )


def test_dist_high20_uses_the_previous_20_sessions_not_today() -> None:
    p = panel()
    t = 150
    p["h"][t, 0] = p["h"][t, 0] * 3  # today's own spike must not enter its own reference high
    p["c"][t, 0] = p["h"][t, 0] / 1.5
    f = feats(p)
    ref = p["h"][t - 20 : t, 0].max()
    assert np.isclose(f["dist_high20_pct"][t, 0], p["c"][t, 0] / ref - 1)


def test_higher_high_count_counts_the_last_10_transitions() -> None:
    p = panel()
    p["h"][:, 0] = np.arange(320) + 1000.0  # strictly rising highs
    p["lo"][:, 0] = p["h"][:, 0] - 5
    f = feats(p)
    assert f["higher_high_count_10d"][200, 0] == 10
    assert f["higher_low_count_10d"][200, 0] == 10


def test_breakout_age_counts_sessions_since_a_close_above_the_prior_20_session_high() -> None:
    t = 120
    p = {k: np.full((t, 1), 100.0) for k in ("o", "h", "lo", "c")}
    p["v"], p["dq"] = np.full((t, 1), 1000.0), np.full((t, 1), 500.0)
    p["c"][60:, 0] = 110.0
    p["h"][60:, 0] = 110.0
    f = feats(p)
    assert f["breakout_age"][60, 0] == 0 and f["breakout_age"][63, 0] == 3
    assert f["breakout_age"][40, 0] == 60  # no breakout yet: capped


def test_volume_ratio_and_up_down_volume_split() -> None:
    p = panel()
    f = feats(p)
    v, c = p["v"], p["c"]
    assert np.isclose(f["volume_ratio_1d"][100, 1], v[100, 1] / v[80:100, 1].mean())
    up = c[91:101, 1] > c[90:100, 1]
    dn = c[91:101, 1] < c[90:100, 1]
    tot = v[91:101, 1].sum()
    assert np.isclose(f["up_volume_ratio_10d"][100, 1], v[91:101, 1][up].sum() / tot)
    assert np.isclose(f["down_volume_ratio_10d"][100, 1], v[91:101, 1][dn].sum() / tot)


def test_atr_distances_are_in_atr_units() -> None:
    p = panel()
    f = feats(p)
    h, lo, c = p["h"], p["lo"], p["c"]
    pc = np.vstack([c[:1], c[:-1]])
    tr = np.maximum.reduce([h - lo, np.abs(h - pc), np.abs(lo - pc)])
    tr[0] = h[0] - lo[0]
    atr = pd.DataFrame(tr).rolling(14, min_periods=14).mean().to_numpy()
    ema = pd.DataFrame(c).ewm(span=20, adjust=False).mean().to_numpy()
    assert np.isclose(
        f["dist_ema20_atr"][150, 3], (c[150, 3] - ema[150, 3]) / atr[150, 3], rtol=1e-4
    )
    assert np.isclose(f["atr_pct_14"][150, 3], atr[150, 3] / c[150, 3], rtol=1e-4)


def test_groups_can_be_asked_for_separately() -> None:
    p = panel()
    only = feats(p, ("volatility",))
    assert only and all(META[n].group == "volatility" for n in only)
    assert "ext3" in only


def test_feature_values_are_float32() -> None:
    assert all(a.dtype == np.float32 for a in feats(panel(), ("price",)).values())
