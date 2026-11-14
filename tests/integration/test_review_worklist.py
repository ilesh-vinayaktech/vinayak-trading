from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.data.review import resolve
from algo.data.review_worklist import impact, worklist
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.integration.test_review import add_review, ts

pytestmark = pytest.mark.integration
EX = date(2025, 6, 12)
NOW = datetime(2026, 11, 7, tzinfo=UTC)


def test_impact_scoring_rules():
    assert impact("demerger", D("-0.1"), member=False, has_prices=False) == 0  # nothing to adjust
    assert impact("demerger", D("-0.1"), member=False, has_prices=True) == 140  # 100 * (1 + 4*0.1)
    assert impact("demerger", D("-0.1"), member=True, has_prices=True) == 420  # Nifty 200: x3
    assert impact("demerger", D("-0.9"), member=False, has_prices=True) == 300  # jump capped at 50%
    assert impact("dividend", None, member=False, has_prices=True) == 5  # no ex-date bar yet
    assert impact("never-seen", D(0), member=False, has_prices=True) == 20  # unknown = "other"


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = {}
    for sym in ("BIG", "SMALL", "NOBARS"):
        ids[sym] = repo.add_instrument(x, sym)
        repo.add_alias(ids[sym], "nse", sym, date(2000, 1, 1))
    for sym, before, after in (("BIG", 1000, 900), ("SMALL", 100, 99)):
        for d, c in ((date(2025, 6, 11), before), (EX, after)):
            conn.execute(
                "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,"
                "dataset_version,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,100,'nse',1,%s)",
                (ids[sym], ts(d), c, c, c, c, NOW),
            )
    conn.execute("INSERT INTO index_snapshot VALUES ('NIFTY200', '2026-11-06', %s)", (ids["BIG"],))
    for sym, kind in (("BIG", "demerger"), ("SMALL", "demerger"), ("NOBARS", "demerger")):
        add_review(conn, ids[sym], EX, kind)
    add_review(conn, ids["SMALL"], EX, "dividend", "Dividend-500%", "percent")
    for d in (date(2025, 1, 2), date(2025, 1, 3)):  # Kite candles: already adjusted, never raw
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,"
            "dataset_version,ingested_at) VALUES (%s,%s,50,50,50,50,100,'kite',1,%s)",
            (ids["SMALL"], ts(d), NOW),
        )
    add_review(conn, ids["SMALL"], date(2025, 1, 3), "demerger")
    return conn


def test_worklist_ranks_by_impact_and_explains_each_row(env):
    rows = worklist(env)["items"]
    assert [(r["symbol"], r["kind"]) for r in rows] == [
        ("BIG", "demerger"),  # Nifty 200, fell 10%
        ("SMALL", "demerger"),  # not in the index, 1% move
        ("SMALL", "dividend"),  # price history but low weight
        ("NOBARS", "demerger"),  # no prices, nothing to adjust: last
        ("SMALL", "demerger"),  # only Kite (adjusted) bars before it: nothing raw to adjust
    ]
    big = rows[0]
    assert big["impact"] == 420 and big["in_nifty200"] and big["has_prices"]
    assert big["move_pct"] == "-10.00" and big["subject"] == "Demerger"
    assert rows[3]["impact"] == 0 and rows[3]["move_pct"] is None and not rows[3]["has_prices"]
    assert rows[4]["impact"] == 0 and not rows[4]["has_prices"] and rows[4]["move_pct"] is None


def test_worklist_counts_and_limit_and_hides_resolved(env):
    out = worklist(env, limit=2)
    assert (out["total"], len(out["items"])) == (5, 2)
    assert out["by_kind"] == {"demerger": 4, "dividend": 1}
    resolve(env, symbol="BIG", ex_date=EX, kind="demerger", method="ignore", note="n", by="t",
            now=NOW)  # fmt: skip
    assert worklist(env)["total"] == 4


def test_worklist_can_be_narrowed_to_one_kind_without_changing_the_counts(env):
    out = worklist(env, kind="dividend")
    assert [r["kind"] for r in out["items"]] == ["dividend"]
    assert out["total"] == 1 and out["by_kind"] == {"demerger": 4, "dividend": 1}
