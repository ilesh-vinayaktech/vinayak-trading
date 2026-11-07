from datetime import date

import psycopg
import pytest

from algo.backtest.engine import run_backtest
from algo.backtest.store import save_run, summary
from algo.backtest.validation.gates import Evidence, Thresholds, evaluate
from algo.backtest.validation.registry import (
    HoldoutAlreadyOpened,
    RegistryError,
    assert_research_window,
    open_holdout,
    params_hash,
    record_trial,
    register,
    save_report,
    trial_count,
    trial_sharpes,
    validation_passed,
)
from algo.strategy.base import Mode
from algo.strategy.lifecycle import promotion_blockers
from tests.support.bt import NOW, REALISTIC, cfg, flat, hold, make_env, put_bars

pytestmark = pytest.mark.integration
T = Thresholds(0.8, 0.95, 0.2, 1.25, 0.25, 0.3, 0.5, 0.2, 252, 2, 0.5, 0.02)
GOOD = Evidence(1.1, 0.97, 0.1, -0.15, -0.2, 0.5, 0.1, 0.6, 0.9, 0.4, 0.3, 0.2, 500, 3, 0.3)
HOLD = (date(2024, 1, 1), date(2024, 12, 31))


@pytest.fixture
def env(conn):
    return make_env(conn)


def new_exp(conn, name="e1", **kw):
    args = dict(name=name, strategy_id="hold", hypothesis="momentum persists", style="long_only",
                param_ranges={"lookback": [60, 250]}, holdout=HOLD, now=NOW)  # fmt: skip
    return register(conn, **{**args, **kw})


def test_registration_requires_a_hypothesis_sane_ranges_and_a_unique_name(conn, env):
    exp = new_exp(conn)
    assert exp > 0
    with pytest.raises(RegistryError, match="hypothesis is required"):
        new_exp(conn, name="e2", hypothesis="  ")
    with pytest.raises(RegistryError, match="range for 'x' must be"):
        new_exp(conn, name="e3", param_ranges={"x": [5, 1]})
    with pytest.raises(RegistryError, match="range for 'x' must be"):
        new_exp(conn, name="e4", param_ranges={"x": [1]})
    with pytest.raises(psycopg.errors.UniqueViolation):
        new_exp(conn)


def test_trials_are_counted_once_per_distinct_configuration(conn, env):
    exp = new_exp(conn)
    assert record_trial(conn, exp, {"lookback": 100}, 0.05, None, NOW) == 1
    assert (
        record_trial(conn, exp, {"lookback": 100}, 0.09, None, NOW) == 1
    )  # same config: no new trial
    assert record_trial(conn, exp, {"lookback": 120}, None, None, NOW) == 2
    assert trial_count(conn, exp) == 2 and trial_sharpes(conn, exp) == [0.05]  # first result kept
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})


def test_a_trial_must_stay_inside_what_was_registered(conn, env):
    exp = new_exp(conn)
    with pytest.raises(RegistryError, match="'skip' was not pre-registered"):
        record_trial(conn, exp, {"skip": 1}, 0.0, None, NOW)
    with pytest.raises(RegistryError, match=r"outside the registered range \[60, 250\]"):
        record_trial(conn, exp, {"lookback": 300}, 0.0, None, NOW)
    assert trial_count(conn, exp) == 0
    with pytest.raises(RegistryError, match="no experiment 999"):
        record_trial(conn, 999, {}, 0.0, None, NOW)


def test_development_runs_must_end_before_the_holdout_starts(conn, env):
    exp = new_exp(conn)
    assert_research_window(conn, exp, date(2023, 12, 29))
    with pytest.raises(RegistryError, match="inside the holdout that starts 2024-01-01"):
        assert_research_window(conn, exp, date(2024, 1, 1))


def test_the_holdout_can_be_opened_exactly_once(conn, env):
    _, a, _ = env
    put_bars(conn, a, flat(100))
    run = save_run(
        conn, run_backtest(conn, hold((a, 1)), cfg(mode=Mode.STRICT, cost=REALISTIC)), NOW
    )
    exp = new_exp(conn)
    open_holdout(conn, exp, run, NOW)
    assert conn.execute(
        "SELECT holdout_run_id, holdout_opened_at IS NOT NULL FROM experiment WHERE experiment_id=%s",
        (exp,),
    ).fetchone() == (run, True)
    with pytest.raises(HoldoutAlreadyOpened, match="already opened"):
        open_holdout(conn, exp, run, NOW)
    with pytest.raises(RegistryError, match="no experiment 999"):
        open_holdout(conn, 999, run, NOW)


def test_only_a_passing_report_on_confirmed_thresholds_lifts_the_validation_blocker(conn, env):
    _, a, _ = env
    put_bars(conn, a, flat(100))
    run = save_run(
        conn, run_backtest(conn, hold((a, 1)), cfg(mode=Mode.STRICT, cost=REALISTIC)), NOW
    )
    exp = new_exp(conn)
    assert not validation_passed(conn, run)
    assert promotion_blockers(summary(conn, run)) != []  # no report at all

    save_report(conn, exp, run, evaluate(GOOD, T, "provisional"), GOOD, 3, NOW)
    assert not validation_passed(conn, run)  # passed, but the thresholds were never confirmed
    assert promotion_blockers(summary(conn, run)) != []

    bad = Evidence()
    save_report(conn, exp, run, evaluate(bad, T, "confirmed"), bad, 3, NOW)
    assert not validation_passed(conn, run)  # a failing report does not count

    save_report(conn, exp, run, evaluate(GOOD, T, "confirmed"), GOOD, 3, NOW)
    assert validation_passed(conn, run)
    assert promotion_blockers(summary(conn, run)) == []
    assert (
        promotion_blockers(summary(conn, run, validation_protocol_passed=False)) != []
    )  # explicit wins
    stored = conn.execute(
        "SELECT n_trials, jsonb_array_length(gates), evidence->>'oos_sharpe' FROM validation_report"
        " WHERE passed AND thresholds_status='confirmed'"
    ).fetchone()
    assert stored == (3, 14, "1.1")
