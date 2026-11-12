import json
from dataclasses import replace
from pathlib import Path

import pytest

from algo.backtest.validation.gates import Evidence, Thresholds, evaluate, load_thresholds

T = Thresholds(0.8, 0.95, 0.2, 1.25, 0.25, 0.3, 0.5, 0.2, 252, 2, 0.5, 0.02)
GOOD = Evidence(
    oos_sharpe=1.1, dsr=0.97, pbo=0.1, max_drawdown=-0.15, benchmark_max_drawdown=-0.2,
    benchmark_sharpe=0.5, plateau_drop=0.1, sharpe_2x_costs=0.6, sharpe_3x_capital=0.9,
    top3_instrument=0.4, top3_month=0.3, top3_trade=0.2, oos_days=500, regimes=3, window_share=0.3,
)  # fmt: skip
CFG = Path(__file__).parents[4] / "config/validation_thresholds.json"
N = 14


def test_good_evidence_passes_every_gate():
    r = evaluate(GOOD, T, "confirmed")
    assert (
        r.passed and r.failures == [] and len(r.gates) == N and r.thresholds_status == "confirmed"
    )


@pytest.mark.parametrize(
    ("change", "gate", "text"),
    [
        ({"oos_days": 251}, "oos_days", "251 OOS observations < required 252"),
        ({"regimes": 1}, "regimes", "1 regimes < required 2"),
        ({"window_share": 0.51}, "window_share", "51% of gains"),
        ({"oos_sharpe": 0.79}, "oos_sharpe", "0.79 < required 0.8"),
        ({"dsr": 0.9}, "deflated_sharpe", "0.900 < required 0.95"),
        ({"pbo": 0.21}, "overfitting_probability", "0.21 > allowed 0.2"),
        ({"max_drawdown": -0.26}, "max_drawdown", "26.0% > owner cap 25%"),
        ({"max_drawdown": -0.2, "benchmark_max_drawdown": -0.1}, "max_drawdown", "2.00x benchmark"),
        ({"benchmark_sharpe": 1.0}, "beats_benchmark", "edge over benchmark 0.10 < required 0.2"),
        ({"plateau_drop": 0.31}, "parameter_plateau", "31% Sharpe lost"),
        ({"sharpe_2x_costs": 0.0}, "survives_2x_costs", "0.00 at 2x costs"),
        ({"sharpe_3x_capital": -0.1}, "survives_3x_capital", "-0.10 at 3x capital"),
        ({"top3_instrument": 0.6}, "concentration_instrument", "60% of gains from 3 instruments"),
        ({"top3_month": 0.6}, "concentration_month", "60% of gains from 3 months"),
        ({"top3_trade": 0.6}, "concentration_trade", "60% of gains from 3 trades"),
    ],
)
def test_each_gate_fails_for_its_own_reason_and_says_why(change, gate, text):
    r = evaluate(replace(GOOD, **change), T)
    assert not r.passed and len(r.failures) == 1
    assert r.failures[0].startswith(gate + ":") and text in r.failures[0]


def test_the_boundary_values_pass():
    edge = replace(
        GOOD, oos_sharpe=0.8, dsr=0.95, pbo=0.2, plateau_drop=0.3, top3_instrument=0.5,
        top3_month=0.5, top3_trade=0.5, oos_days=252, regimes=2, window_share=0.5,
        benchmark_sharpe=0.5, max_drawdown=-0.25, benchmark_max_drawdown=-0.2,
    )  # fmt: skip
    assert evaluate(edge, T).passed  # DD ratio exactly 1.25, owner cap exactly 25%


def test_the_drawdown_ratio_is_not_applicable_when_the_benchmark_barely_drew_down():
    g = next(
        x for x in evaluate(replace(GOOD, max_drawdown=-0.2, benchmark_max_drawdown=-0.01), T).gates
        if x.name == "max_drawdown"
    )  # fmt: skip
    assert g.passed and "ratio n/a" in g.detail
    capped = replace(GOOD, max_drawdown=-0.3, benchmark_max_drawdown=-0.01)
    assert "owner cap" in evaluate(capped, T).failures[0]  # the absolute cap still applies


@pytest.mark.parametrize("field", list(vars(GOOD)))
def test_missing_evidence_fails_that_gate_rather_than_passing_silently(field):
    r = evaluate(replace(GOOD, **{field: None}), T)
    assert not r.passed and any("evidence missing" in f for f in r.failures)


def test_an_empty_evidence_record_fails_everything():
    assert len(evaluate(Evidence(), T).failures) == N


def test_thresholds_load_from_the_config_with_the_owners_confirmation():
    t, status = load_thresholds(CFG, "long_only")
    assert (t.min_oos_sharpe, t.max_pbo, t.owner_max_drawdown, t.min_oos_days, status) == (
        0.8, 0.2, 0.25, 252, "confirmed"
    )  # fmt: skip
    m = load_thresholds(CFG, "market_neutral")[0]
    assert (m.min_oos_sharpe, m.owner_max_drawdown) == (1.0, 0.15)


def test_unknown_style_and_malformed_keys_are_refused(tmp_path):
    with pytest.raises(ValueError, match="no thresholds for style 'x'"):
        load_thresholds(CFG, "x")
    bad = tmp_path / "t.json"
    bad.write_text(json.dumps({"long_only": {"min_oos_sharpe": 1}}))
    with pytest.raises(ValueError, match="keys differ"):
        load_thresholds(bad, "long_only")
    bad.write_text(json.dumps({"long_only": {**vars(T), "extra": 1}}))
    with pytest.raises(ValueError, match="extra"):
        load_thresholds(bad, "long_only")
    ok = tmp_path / "o.json"
    ok.write_text(json.dumps({"long_only": vars(T)}))
    assert load_thresholds(ok, "long_only") == (T, "")
