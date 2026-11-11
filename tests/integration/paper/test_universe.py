from datetime import date
from pathlib import Path

import pytest

from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper.universe import UNIVERSES, UniverseError, current_universe

pytestmark = pytest.mark.integration
HEADER = "Company Name,Industry,Symbol,Series,ISIN Code\n"


def put_list(lake: Path, day: str, symbols, version=1, name="nifty200_list"):
    d = lake / "raw/niftyindices" / name / f"dt={day}"
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
    members, meta = current_universe(conn, lake, date(2026, 11, 12))
    assert members.on(date(2026, 11, 12)) == frozenset(ids.values())
    assert members.ever() == sorted(ids.values())
    assert meta == {
        "universe": "nifty200",
        "lists": {"nifty200_list": "2026-09-25"},
        "listed": 3,
        "mapped": 3,
        "unmatched": [],
    }


def test_symbols_we_cannot_map_are_reported_not_hidden(env):
    conn, ids, lake = env
    put_list(lake, "2026-09-25", ["AAA", "ZZZ", "BBB"])
    members, meta = current_universe(conn, lake, date(2026, 11, 12))
    assert members.ever() == sorted([ids["AAA"], ids["BBB"]])
    assert (meta["listed"], meta["mapped"], meta["unmatched"]) == (3, 2, ["ZZZ"])


def test_no_list_or_an_old_one_is_refused_so_a_stale_index_is_never_traded(env):
    conn, _, lake = env
    with pytest.raises(UniverseError, match="no nifty200_list"):
        current_universe(conn, lake, date(2026, 11, 12))
    put_list(lake, "2026-03-20", ["AAA"])
    with pytest.raises(UniverseError, match="days old"):
        current_universe(conn, lake, date(2026, 11, 12))
    assert current_universe(conn, lake, date(2026, 11, 12), max_age_days=300)[1]["listed"] == 1


def test_the_universe_is_chosen_by_name_and_the_bigger_ones_are_unions_of_lists(env):
    conn, ids, lake = env
    put_list(lake, "2026-10-01", ["AAA"], name="nifty50_list")
    put_list(
        lake, "2026-10-01", ["BBB", "AAA"], name="niftynext50_list"
    )  # a stock in two lists counts once
    put_list(lake, "2026-10-01", ["CCC"], name="niftymidcap100_list")
    put_list(lake, "2026-10-01", ["AAA", "BBB", "CCC"], name="nifty500_list")
    day = date(2026, 11, 12)
    got = {
        k: current_universe(conn, lake, day, k)[0].ever()
        for k in ("nifty50", "nifty100", "midcap100", "nifty500")
    }
    a, b, c = ids["AAA"], ids["BBB"], ids["CCC"]
    assert got == {
        "nifty50": [a],
        "nifty100": sorted([a, b]),
        "midcap100": [c],
        "nifty500": sorted([a, b, c]),
    }
    meta = current_universe(conn, lake, day, "nifty100")[1]
    assert meta["universe"] == "nifty100" and meta["lists"] == {
        "nifty50_list": "2026-10-01",
        "niftynext50_list": "2026-10-01",
    }
    assert (meta["listed"], meta["mapped"]) == (3, 2)  # AAA, BBB, AAA: the same stock twice is one


def test_an_unknown_universe_name_is_refused_and_every_known_one_has_a_label(env):
    conn, _, lake = env
    with pytest.raises(UniverseError, match="unknown universe"):
        current_universe(conn, lake, date(2026, 11, 12), "nifty9000")
    assert set(UNIVERSES) == {"nifty50", "nifty100", "nifty200", "midcap100", "nifty500"}
    assert all(label for label, _ in UNIVERSES.values())
