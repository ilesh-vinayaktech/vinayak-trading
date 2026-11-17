# ruff: noqa: E501
"""A generated definition can be paper traded only after its study passed the one global holdout. ENGINEERING_TEST_ONLY: synthetic prices.

Callers: pytest. Uses algo.paper.definitions, the real holdout batch (algo.research.holdout_batch) and the daily runner.
User's instruction: "keep the order": global holdout first, paper trading after it."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from psycopg.types.json import Jsonb

from algo.core.clock import SimClock
from algo.data.amfi_caps import CapList, CapRow
from algo.data.market_caps import load_list
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper import book, configs, definitions
from algo.paper.runner import run_day
from algo.research import holdout_batch as hb
from algo.research import holdout_lock
from algo.research.holdout_lock import Lock
from tests.support.market import NOW, put, sessions
from tests.support.portal import add_user
from tests.support.research_lock import write_lock_file

pytestmark = pytest.mark.integration
JAN = date(2025, 1, 1)
DAYS = sessions(520)
LOCK = Lock(date(2024, 12, 31), date(2025, 1, 1), date(2026, 11, 13))
DEFINITION = {
    "strategy_id": "RISERS_001", "version": 1, "description": "Hold the strongest 20-day risers until they fall.",
    "universe": "MEMBERS", "timeframe": "DAILY",
    "entry": {"all": [{"feature": "ret_20d", "op": ">", "value": 0}]},
    "exit": {"any": [{"feature": "ret_20d", "op": "<", "value": 0}]},
    "ranking": {"feature": "ret_20d", "order": "DESC"},
    "position": {"max_positions": 5, "sizing": "EQUAL_WEIGHT"}, "risk": {"max_position_percent": 20},
    "rebalance": "DAILY",
}  # fmt: skip
SPEC = {
    "name": "RISERS_001 v1 test", "definition": DEFINITION,
    "universe": {"segments": ["large", "mid"], "min_history_sessions": 30},
}  # fmt: skip


def at(day):
    return datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=13)


@pytest.fixture
def env(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "kite")
    monkeypatch.setattr(holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "lock.json", LOCK))
    migrate(conn)
    holdout_lock.anchor(conn, LOCK, by="owner", reason="test", now=NOW)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    names = ("FAST", "EXTRA", "FALLING")
    ids = {s: repo.add_instrument(x, s, isin=f"INE00000000{i}") for i, s in enumerate(names, 1)}
    put(conn, ids["FAST"], "0.004", DAYS)
    put(conn, ids["EXTRA"], "0.001", DAYS)
    put(conn, ids["FALLING"], "-0.002", DAYS)
    rows = tuple(
        CapRow(i, f"INE00000000{i}", s, f"Co {i}", D(1000 - i)) for i, s in enumerate(names, 1)
    )
    load_list(conn, CapList(date(2023, 6, 30), rows), "u1", "s1", NOW)
    uid = add_user(conn, SimClock(NOW), "TRADER", "jane@example.com")
    book.create_account(conn, uid, strategy_id="trend_pullback", params={}, initial_cash=D(1_000_000), started_on=JAN, now=NOW)  # fmt: skip
    conn.execute(
        "SET session_replication_role = replica"
    )  # the report's run row is not what is tested here
    conn.execute(
        "INSERT INTO experiment (experiment_id, name, strategy_id, hypothesis, style, param_ranges, holdout_start, holdout_end, registered_at, study, study_sha256)"
        " VALUES (1, 'study 1', 'dsl', 'h', 'long_only', '{}', '2024-01-01', '2024-12-31', %s, %s, 's1')",
        (NOW, Jsonb({"code": {"commit": "abc", "dirty": False}, "spec": SPEC})),
    )
    conn.execute(
        "INSERT INTO study_dataset (experiment_id, dataset_sha256, manifest, sealed_at) VALUES (1,'d1','{}',%s)",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO validation_report (report_id, experiment_id, run_id, passed, thresholds_status, n_trials, evidence, gates, refs, created_at)"
        " VALUES (1, 1, 1, true, 'confirmed', 3, '{}', '[]', %s, %s)",
        (Jsonb({"chosen": {"max_positions": 5}}), NOW),
    )
    conn.execute("SET session_replication_role = DEFAULT")
    return conn, ids, uid, tmp_path


def holdout(conn, verdict):
    """The one global holdout, consumed with this verdict for study 1."""
    bid = hb.register(conn, by="owner", now=NOW)
    cand = hb.Candidate("study-1", "momentum", "1", "p1", "d1", "s1", 1)
    hb.freeze(conn, bid, hb.Manifest(bid, (cand,), {"momentum": 30}, LOCK.holdout_start, LOCK.holdout_end, "holm", "1", hb.EVALUATOR_VERSION), NOW)  # fmt: skip
    hb.evaluate(conn, bid, lambda cap, m: hb.Results({("study-1", "holdout_sharpe"): verdict}, {}), lambda _g: object(), NOW)  # fmt: skip


def test_before_the_global_holdout_a_passed_definition_is_waiting_and_cannot_start(env):
    conn, _, uid, _ = env
    assert definitions.candidates(conn) == [{"experiment_id": 1, "strategy_id": "RISERS_001", "version": 1, "name": SPEC["name"], "state": "awaiting_holdout"}]  # fmt: skip
    with pytest.raises(book.PaperError, match="not passed the global holdout"):
        definitions.start(conn, uid, 1)
    assert book.get_account(conn, uid)["strategy_id"] == "trend_pullback"


def test_a_definition_that_failed_the_global_holdout_cannot_start(env):
    conn, _, uid, _ = env
    holdout(conn, "FAIL")
    assert definitions.candidates(conn)[0]["state"] == "failed_holdout"
    with pytest.raises(book.PaperError, match="not passed the global holdout"):
        definitions.start(conn, uid, 1)


def test_an_unknown_study_and_a_missing_account_are_refused(env):
    conn, _, uid, _ = env
    holdout(conn, "PASS")
    with pytest.raises(book.PaperError, match="no such definition study"):
        definitions.start(conn, uid, 99)
    with pytest.raises(book.PaperError, match="no paper account"):
        definitions.start(conn, add_user(conn, SimClock(NOW), "TRADER", "joe@example.com"), 1)


def test_a_definition_that_passed_the_global_holdout_starts_and_the_runner_trades_it(env):
    conn, ids, uid, lake = env
    holdout(conn, "PASS")
    assert definitions.candidates(conn)[0]["state"] == "ready"
    assert definitions.start(conn, uid, 1) == SPEC["name"]
    acct = book.get_account(conn, uid)
    assert (acct["strategy_id"], acct["universe"], acct["params"]) == (
        "dsl",
        "segments",
        {"max_positions": 5},
    )
    assert (
        acct["definition"]["definition"] == DEFINITION and acct["definition"]["experiment_id"] == 1
    )
    out = run_day(conn, uid, day=JAN, now=at(JAN), lake_root=lake)
    assert out.status == "PROPOSED", out.detail
    rows = conn.execute(
        "SELECT instrument_id, side FROM paper_order WHERE user_id=%s ORDER BY instrument_id",
        (uid,),
    ).fetchall()
    assert rows == [
        (ids["FAST"], "BUY"),
        (ids["EXTRA"], "BUY"),
    ]  # the riser and the slow riser; the faller never qualifies
    ran = conn.execute(
        "SELECT strategy_id, detail FROM paper_run WHERE user_id=%s", (uid,)
    ).fetchone()
    assert ran[0] == "RISERS_001" and ran[1]["universe"]["segments"] == ["large", "mid"]
    with pytest.raises(book.PaperError, match="fixed by the study"):
        book.update_settings(conn, uid, max_instruments=10)


def test_moving_to_a_saved_strategy_takes_the_definition_off_the_account(env):
    conn, _, uid, _ = env
    holdout(conn, "PASS")
    definitions.start(conn, uid, 1)
    back = configs.create(conn, uid, name="Trend", universe="nifty100", max_instruments=None, timeframe="1D", params={"trend_sma": 200, "entry_rsi": 25, "exit_rsi": 60, "max_positions": 10}, now=NOW)  # fmt: skip
    configs.use(conn, uid, back)
    acct = book.get_account(conn, uid)
    assert acct["strategy_id"] == "trend_pullback" and acct["definition"] is None


def test_a_monthly_definition_decides_once_a_month_in_paper_like_it_did_in_the_study(env):
    conn, _, uid, lake = env
    holdout(conn, "PASS")
    definitions.start(conn, uid, 1)
    conn.execute("UPDATE paper_account SET definition = jsonb_set(definition, '{definition,rebalance}', '\"MONTHLY\"') WHERE user_id=%s", (uid,))  # fmt: skip
    feb = next(d for d in DAYS if d >= date(2025, 2, 1))
    day2 = next(d for d in DAYS if d > JAN)
    first = run_day(conn, uid, day=JAN, now=at(JAN), lake_root=lake)
    again = run_day(conn, uid, day=day2, now=at(day2), lake_root=lake)
    later = run_day(conn, uid, day=feb, now=at(feb), lake_root=lake)
    assert (first.status, again.status) == (
        "PROPOSED",
        "NO_CHANGE",
    )  # the same month: the strategy keeps its targets
    assert (
        later.status in ("PROPOSED", "NO_CHANGE")
        and later.detail.get("reason") != "the strategy kept its targets"
    )  # a new month decides again


def test_a_passed_study_with_no_chosen_settings_is_not_offered(env):
    conn, _, _, _ = env
    conn.execute("UPDATE validation_report SET refs='{}'::jsonb")
    assert definitions.candidates(conn) == []
