"""Holdout policy v3 section 7: the evaluator reaches the database only through a guarded handle."""

import pytest

from algo.research import holdout_guard as g


class Fake:
    def __init__(self):
        self.seen = []

    def execute(self, sql, params=None, **kw):
        self.seen.append(sql)
        return "rows"


def guarded():
    f = Fake()
    return g.guard(f), f


def test_source_inputs_and_the_studys_own_record_are_reachable():
    h, f = guarded()
    for sql in (
        "SELECT ts, close FROM bar_1d WHERE instrument_id=%s",
        "SELECT * FROM corporate_action a JOIN action_resolution r ON r.id=a.id",
        "SELECT period_end FROM market_cap_list",
        "SELECT experiment_id, study FROM experiment WHERE study_sha256=%s",
        "WITH l AS (SELECT * FROM partition_load) SELECT * FROM l",
        "SELECT * FROM benchmark b LEFT JOIN LATERAL (SELECT 1 FROM benchmark_observation o WHERE o.benchmark_id=b.benchmark_id) s ON true",
        "SELECT * FROM public.instrument",
    ):
        assert h.execute(sql, (1,)) == "rows", sql
    assert len(f.seen) == 7 and len(h.log) == 7


@pytest.mark.parametrize(
    "table",
    ["definition_signal_series", "definition_signal_day", "paper_order", "paper_run", "paper_equity", "backtest_run", "backtest_trade", "feature_value", "feature_run",
     "alpha_hypothesis", "holdout_verdict", "holdout_report", "study_trial", "experiment_trial", "study_run", "screener_snapshot", "strategy_config", "portal_user"],
)  # fmt: skip
def test_derived_and_unrelated_tables_are_refused_not_quietly_answered(table):
    h, f = guarded()
    for sql in (
        f"SELECT * FROM {table}",
        f"SELECT 1 FROM instrument i JOIN {table} t ON true",
        f"WITH x AS (SELECT * FROM {table}) SELECT * FROM x",
    ):
        with pytest.raises(g.GuardError, match=table):
            h.execute(sql)
    assert f.seen == []  # nothing reached the database


def test_the_evaluator_reads_and_never_writes():
    h, f = guarded()
    for sql in (
        "INSERT INTO bar_1d VALUES (1)",
        "UPDATE instrument SET symbol='x'",
        "DELETE FROM bar_1d",
        "TRUNCATE bar_1d",
        "  drop table instrument",
    ):
        with pytest.raises(g.GuardError, match="never writes"):
            h.execute(sql)
    assert f.seen == []


def test_the_handle_has_no_other_way_to_the_database():
    h, _ = guarded()
    for name in (
        "cursor",
        "commit",
        "rollback",
        "transaction",
        "pipeline",
        "close",
        "_conn_raw",
        "__dict__",
    ):
        assert not hasattr(h, name), name


def test_only_the_batch_module_can_make_one():
    with pytest.raises(g.GuardError, match="only the batch module"):
        g.GuardedConnection(object(), Fake())  # type: ignore[arg-type]


def test_tables_of_ignores_cte_names_and_schemas():
    assert g.tables_of(
        "WITH a AS (SELECT * FROM bar_1d), b AS (SELECT * FROM a) SELECT * FROM b JOIN public.instrument i ON true"
    ) == {"bar_1d", "instrument"}
