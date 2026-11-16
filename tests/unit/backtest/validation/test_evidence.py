import pytest

from algo.backtest.validation.evidence import Inputs, assemble
from algo.backtest.validation.stats import annualised_sharpe, max_drawdown

OOS = [0.01, -0.005, 0.012, 0.0, 0.008, -0.002] * 50


def test_nothing_supplied_leaves_every_gate_input_missing_except_what_the_oos_series_gives():
    e = assemble(Inputs(OOS))
    assert (
        e.oos_sharpe == annualised_sharpe(OOS)
        and e.oos_days == 300
        and e.max_drawdown == max_drawdown(OOS)
    )
    assert e.dsr is not None  # N defaults to 1
    for name in ("pbo", "benchmark_max_drawdown", "benchmark_sharpe", "plateau_drop", "sharpe_2x_costs",
                 "sharpe_3x_capital", "top3_instrument", "top3_month", "top3_trade", "regimes",
                 "window_share"):  # fmt: skip
        assert getattr(e, name) is None, name


def test_an_empty_oos_series_yields_no_evidence():
    e = assemble(Inputs([]))
    assert e.oos_days is None and e.max_drawdown is None and e.oos_sharpe is None


def test_a_benchmark_on_other_dates_is_ignored_rather_than_misaligned():
    assert assemble(Inputs(OOS, benchmark_returns=OOS[:-1])).benchmark_sharpe is None
    b = [x / 2 for x in OOS]
    e = assemble(Inputs(OOS, benchmark_returns=b))
    assert e.benchmark_sharpe == annualised_sharpe(b) and e.benchmark_max_drawdown == max_drawdown(
        b
    )


def test_more_trials_lower_the_deflated_sharpe():
    few = assemble(Inputs(OOS, n_trials=1)).dsr
    many = assemble(Inputs(OOS, n_trials=50, trial_sharpes=[0.0, 0.05, 0.1, 0.15])).dsr
    assert many < few
    assert assemble(Inputs(OOS, n_trials=0)).dsr == few  # a zero count is treated as one


def test_plateau_pbo_and_concentration_and_windows_are_derived():
    trials = [[0.01 * ((i + k) % 3 - 1) + 0.002 * k for i in range(80)] for k in range(3)]
    e = assemble(
        Inputs(
            OOS, base_sharpe=1.0, neighbour_sharpes=[0.9, 0.6, None], trial_returns=trials,
            by_instrument={"A": 6.0, "B": 4.0, "C": -1.0}, by_month={"m1": 1.0, "m2": 1.0},
            by_trade={"t": 5.0}, regime_labels=["bull", "bull", "bear"], window_returns=[0.1, 0.3, -0.2],
            returns_2x_costs=OOS, returns_3x_capital=OOS,
        )
    )  # fmt: skip
    assert e.plateau_drop == 1.0  # the undefined neighbour is a collapse
    assert e.pbo is not None and 0 <= e.pbo <= 1
    assert (e.top3_instrument, e.top3_month, e.top3_trade) == (1.0, 1.0, 1.0)
    assert e.regimes == 2 and e.window_share == pytest.approx(0.75)
    assert e.sharpe_2x_costs == e.sharpe_3x_capital == annualised_sharpe(OOS)


def test_no_positive_window_means_no_window_evidence():
    assert assemble(Inputs(OOS, window_returns=[-0.1, -0.2])).window_share is None


def test_a_grid_of_near_identical_variants_gets_a_sharpe_lower_bound_and_a_grid_of_different_ones_does_not():
    import random

    rng = random.Random(3)
    base = [0.0008 + rng.gauss(0, 0.01) for _ in range(300)]
    twins = [[x * k for x in base] for k in (1.0, 1.1, 0.9)]
    different = [[rng.gauss(0, 0.01) for _ in range(300)] for _ in range(3)]
    ev_t = assemble(Inputs(oos_returns=base, trial_returns=twins))
    ev_d = assemble(Inputs(oos_returns=base, trial_returns=different))
    assert (
        ev_t.pbo_twins
        and ev_t.oos_sharpe_lower is not None
        and ev_t.oos_sharpe_lower < ev_t.oos_sharpe
    )
    assert not ev_d.pbo_twins and ev_d.oos_sharpe_lower is None and ev_d.pbo is not None
    assert assemble(Inputs(oos_returns=base, trial_returns=twins)) == ev_t  # deterministic


def test_when_nothing_was_selected_the_overfitting_gate_uses_the_sharpe_lower_bound_whatever_the_variants_look_like():
    import random

    rng = random.Random(5)
    base = [0.0008 + rng.gauss(0, 0.01) for _ in range(300)]
    different = [
        [rng.gauss(0, 0.01) for _ in range(300)] for _ in range(3)
    ]  # variants that look nothing alike: PBO would normally apply
    chosen = assemble(Inputs(oos_returns=base, trial_returns=different))
    fixed = assemble(Inputs(oos_returns=base, trial_returns=different, no_selection=True))
    assert (
        not chosen.pbo_twins and fixed.pbo_twins and fixed.oos_sharpe_lower is not None
    )  # no choosing, so no overfitting to measure
