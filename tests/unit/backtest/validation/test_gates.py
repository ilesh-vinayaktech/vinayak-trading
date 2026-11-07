import json
from dataclasses import replace
from pathlib import Path

import pytest

from algo.backtest.validation.gates import Evidence, Thresholds, evaluate, load_thresholds

T = Thresholds(0.8, 0.95, 0.5, 1.5, 0.35, 0.3, 0.6, 0.0)
GOOD = Evidence(
    oos_sharpe=1.1, dsr=0.97, pbo=0.2, max_drawdown=-0.2, benchmark_max_drawdown=-0.3,
    benchmark_sharpe=0.5, plateau_drop=0.1, sharpe_2x_costs=0.6, sharpe_3x_capital=0.9,
    top3_concentration=0.4,
)  # fmt: skip
CFG = Path(__file__).parents[4] / "config/validation_thresholds.json"


def test_good_evidence_passes_every_gate():
    r = evaluate(GOOD, T, "confirmed")
    assert (
        r.passed and r.failures == [] and len(r.gates) == 9 and r.thresholds_status == "confirmed"
    )


@pytest.mark.parametrize(
    ("change", "gate", "text"),
    [
        ({"oos_sharpe": 0.79}, "oos_sharpe", "0.79 < required 0.8"),
        ({"dsr": 0.9}, "deflated_sharpe", "0.900 < required 0.95"),
        ({"pbo": 0.51}, "overfitting_probability", "0.51 > allowed 0.5"),
        ({"max_drawdown": -0.36, "benchmark_max_drawdown": -0.5}, "max_drawdown", "36.0%"),
        ({"max_drawdown": -0.31, "benchmark_max_drawdown": -0.2}, "max_drawdown", "31.0% > limit"),
        ({"benchmark_sharpe": 1.1}, "beats_benchmark", "edge over benchmark 0.00"),
        ({"plateau_drop": 0.31}, "parameter_plateau", "31% Sharpe lost"),
        ({"sharpe_2x_costs": 0.0}, "survives_2x_costs", "0.00 at 2x costs"),
        ({"sharpe_3x_capital": -0.1}, "survives_3x_capital", "-0.10 at 3x capital"),
        ({"top3_concentration": 0.7}, "concentration", "70% of gains"),
    ],
)
def test_each_gate_fails_for_its_own_reason_and_says_why(change, gate, text):
    r = evaluate(replace(GOOD, **change), T)
    assert not r.passed and len(r.failures) == 1
    assert r.failures[0].startswith(gate + ":") and text in r.failures[0]


def test_the_boundary_values_pass():
    edge = replace(
        GOOD, oos_sharpe=0.8, dsr=0.95, pbo=0.5, plateau_drop=0.3, top3_concentration=0.6
    )
    assert evaluate(edge, T).passed


@pytest.mark.parametrize("field", list(vars(GOOD)))
def test_missing_evidence_fails_that_gate_rather_than_passing_silently(field):
    r = evaluate(replace(GOOD, **{field: None}), T)
    assert not r.passed and any("evidence missing" in f for f in r.failures)


def test_an_empty_evidence_record_fails_everything():
    assert len(evaluate(Evidence(), T).failures) == 9


def test_thresholds_load_from_the_config_and_are_provisional_until_confirmed():
    t, status = load_thresholds(CFG, "long_only")
    assert (t.min_oos_sharpe, t.min_dsr, t.plateau_tolerance, status) == (
        0.8,
        0.95,
        0.3,
        "provisional",
    )
    assert load_thresholds(CFG, "market_neutral")[0].min_oos_sharpe == 1.0


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
