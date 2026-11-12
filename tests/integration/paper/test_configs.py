from datetime import UTC, date, datetime
from decimal import Decimal as D
from uuid import uuid4

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.paper import book, configs
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
S = {"universe": "nifty100", "max_instruments": 50, "timeframe": "1D", "params": {"entry_rsi": 30}}


@pytest.fixture
def env(conn):
    migrate(conn)
    clock = SimClock(NOW)
    return (
        conn,
        add_user(conn, clock, "TRADER", "jane@example.com"),
        add_user(conn, clock, "TRADER", "bob@example.com"),
    )


def make(conn, user, name="Cautious", **over):
    return configs.create(conn, user, name=name, now=NOW, **{**S, **over})


def open_account(conn, user):
    book.create_account(
        conn,
        user,
        strategy_id="trend_pullback",
        params={},
        initial_cash=D(1000),
        started_on=date(2026, 11, 2),
        now=NOW,
    )


def test_a_config_is_saved_listed_and_read_back_for_its_owner_only(env):
    conn, jane, bob = env
    cid = make(conn, jane)
    got = configs.get(conn, jane, cid)
    assert got["name"] == "Cautious" and got["strategy_id"] == "trend_pullback"
    assert (got["universe"], got["max_instruments"], got["timeframe"]) == ("nifty100", 50, "1D")
    assert got["params"] == {"entry_rsi": 30} and got["in_use"] is False
    assert [c["config_id"] for c in configs.list_for(conn, jane)] == [cid]
    assert configs.list_for(conn, bob) == []
    assert configs.get(conn, bob, cid) is None and configs.get(conn, jane, uuid4()) is None


def test_names_are_unique_per_owner_and_settings_are_checked(env):
    conn, jane, bob = env
    make(conn, jane)
    make(conn, bob)  # another person may reuse the name
    with pytest.raises(configs.ConfigError, match="already have"):
        make(conn, jane)
    with pytest.raises(configs.ConfigError, match="name"):
        make(conn, jane, name="  ")
    with pytest.raises(configs.ConfigError, match="name"):
        make(conn, jane, name="x" * 61)
    with pytest.raises(configs.ConfigError, match="unknown universe"):
        make(conn, jane, name="B", universe="nifty7")
    with pytest.raises(configs.ConfigError, match="daily"):
        make(conn, jane, name="C", timeframe="1h")
    with pytest.raises(configs.ConfigError, match="between 5 and 500"):
        make(conn, jane, name="D", max_instruments=3)


def test_saving_a_config_changes_the_accounts_that_use_it(env):
    conn, jane, bob = env
    cid = make(conn, jane)
    open_account(conn, jane)
    configs.use(conn, jane, cid)
    acct = book.get_account(conn, jane)
    assert (acct["universe"], acct["max_instruments"], acct["params"]) == (
        "nifty100",
        50,
        S["params"],
    )
    assert acct["config_id"] == cid and configs.get(conn, jane, cid)["in_use"] is True
    configs.update(
        conn, jane, cid, name="Bolder", **{**S, "universe": "nifty50", "params": {"entry_rsi": 20}}
    )
    acct = book.get_account(conn, jane)
    assert (acct["universe"], acct["params"]) == ("nifty50", {"entry_rsi": 20})
    assert configs.get(conn, jane, cid)["name"] == "Bolder"
    make(conn, jane, name="Other")  # renaming onto a taken name is refused and changes nothing
    with pytest.raises(configs.ConfigError, match="already have"):
        configs.update(conn, jane, cid, name="Other", **S)
    assert configs.get(conn, jane, cid)["name"] == "Bolder"
    with pytest.raises(configs.ConfigError, match="no such"):
        configs.update(conn, bob, cid, name="Mine", **S)


def test_using_a_config_needs_an_account_and_your_own_config(env):
    conn, jane, bob = env
    cid = make(conn, jane)
    with pytest.raises(configs.ConfigError, match="no paper account"):
        configs.use(conn, jane, cid)
    open_account(conn, bob)
    with pytest.raises(configs.ConfigError, match="no such"):
        configs.use(conn, bob, cid)  # not bob's


def test_a_config_in_use_cannot_be_deleted_and_an_unused_one_can(env):
    conn, jane, bob = env
    used, spare = make(conn, jane), make(conn, jane, name="Spare")
    open_account(conn, jane)
    configs.use(conn, jane, used)
    with pytest.raises(configs.ConfigError, match="in use"):
        configs.delete(conn, jane, used)
    with pytest.raises(configs.ConfigError, match="no such"):
        configs.delete(conn, bob, spare)
    configs.delete(conn, jane, spare)
    assert [c["config_id"] for c in configs.list_for(conn, jane)] == [used]
