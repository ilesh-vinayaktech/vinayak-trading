from datetime import date
from pathlib import Path

import pytest

from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper.universe import UniverseError, current_nifty200

pytestmark = pytest.mark.integration
HEADER = "Company Name,Industry,Symbol,Series,ISIN Code\n"


def put_list(lake: Path, day: str, symbols, version=1):
    d = lake / "raw/niftyindices/nifty200_list" / f"dt={day}"
    d.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"{s} Ltd.,Industry,{s},EQ,INE000{i:06d}\n" for i, s in enumerate(symbols))
    (d / f"v{version}.bin").write_bytes(("﻿" + HEADER + rows).encode("utf-8"))


@pytest.fixture
def env(conn, tmp_path):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = {}
    for sym in ("AAA", "BBB", "CCC"):
        ids[sym] = repo.add_instrument(x, sym)
        repo.add_alias(ids[sym], "nse", sym, date(2000, 1, 1))
    return conn, ids, tmp_path


def test_the_latest_list_on_or_before_the_day_is_the_universe_and_its_date_is_reported(env):
    conn, ids, lake = env
    put_list(lake, "2026-03-20", ["AAA"])
    put_list(lake, "2026-09-25", ["AAA", "BBB"], version=1)
    put_list(
        lake, "2026-09-25", ["AAA", "BBB", "CCC"], version=2
    )  # a re-issued file of the same day wins
    put_list(lake, "2026-12-01", ["AAA"])  # after the decision day: not yet known
    members, meta = current_nifty200(conn, lake, date(2026, 11, 12))
    assert members.on(date(2026, 11, 12)) == frozenset(ids.values())
    assert members.ever() == sorted(ids.values())
    assert meta == {"list_date": "2026-09-25", "listed": 3, "mapped": 3, "unmatched": []}


def test_symbols_we_cannot_map_are_reported_not_hidden(env):
    conn, ids, lake = env
    put_list(lake, "2026-09-25", ["AAA", "ZZZ", "BBB"])
    members, meta = current_nifty200(conn, lake, date(2026, 11, 12))
    assert members.ever() == sorted([ids["AAA"], ids["BBB"]])
    assert (meta["listed"], meta["mapped"], meta["unmatched"]) == (3, 2, ["ZZZ"])


def test_no_list_or_an_old_one_is_refused_so_a_stale_index_is_never_traded(env):
    conn, _, lake = env
    with pytest.raises(UniverseError, match="no Nifty 200 list"):
        current_nifty200(conn, lake, date(2026, 11, 12))
    put_list(lake, "2026-03-20", ["AAA"])
    with pytest.raises(UniverseError, match="days old"):
        current_nifty200(conn, lake, date(2026, 11, 12))
    assert current_nifty200(conn, lake, date(2026, 11, 12), max_age_days=300)[1]["listed"] == 1
