from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.data.identity_migration import MigrationError, migrate_isin_change
from algo.data.reader import BarReader
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.integration.test_reader import action, bar

pytestmark = pytest.mark.integration
CHANGE = date(2024, 1, 5)
NOW = datetime(2026, 11, 9, tzinfo=UTC)
PRE = [(date(2024, 1, 2), D(20000)), (date(2024, 1, 3), D(20100)), (date(2024, 1, 4), D(20200))]
POST = [(date(2024, 1, 5), D(2030)), (date(2024, 1, 8), D(2040))]
FIRST, LAST = date(2024, 1, 2), date(2024, 1, 8)
KW = dict(
    old_isin="INE239A01016", change=CHANGE, first_observed=date(2010, 1, 8),
    evidence=["NSE circular CML60084"], decision_id=15, now=NOW,
)  # fmt: skip


@pytest.fixture
def issuer(conn):
    """Today's layout: ONE instrument holds everything, with an alias that starts before the change."""
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "NESTLEIND")
    conn.execute(
        "UPDATE instrument SET isin='INE239A01024', name='Nestle India' WHERE instrument_id=%s",
        (iid,),
    )
    repo.add_alias(iid, "nse", "NESTLEIND", date(2023, 8, 1))
    conn.execute(
        "INSERT INTO instrument_terms (instrument_id, valid_from, lot_size, tick_size, qty_step,"
        " multiplier) VALUES (%s,'2023-08-01',1,0.05,1,1)",
        (iid,),
    )
    for d, c in PRE + POST:
        bar(conn, iid, d, c)
    action(conn, iid, date(2023, 6, 1), "dividend", amount=D(75))
    action(conn, iid, CHANGE, "split", num=D(10), den=D(1))
    return conn, iid


def state(conn):
    def rows(sql):
        return conn.execute(sql).fetchall()

    return {
        "instruments": rows("SELECT count(*) FROM instrument"),
        "bars": rows("SELECT instrument_id, count(*) FROM bar_1d GROUP BY 1 ORDER BY 1"),
        "actions": rows(
            "SELECT instrument_id, count(*) FROM corporate_action GROUP BY 1 ORDER BY 1"
        ),
        "aliases": rows(
            "SELECT instrument_id, valid_from, valid_to FROM instrument_alias ORDER BY 1, 2"
        ),
        "terms": rows(
            "SELECT instrument_id, valid_from, valid_to FROM instrument_terms ORDER BY 1, 2"
        ),
        "relationships": rows("SELECT count(*) FROM corporate_action_relationship"),
    }


def test_a_dry_run_does_every_step_and_check_then_leaves_nothing_behind(issuer):
    conn, iid = issuer
    before = state(conn)
    audit = migrate_isin_change(conn, new_id=iid, **KW)  # dry_run defaults to True
    assert audit["applied"] is False and all(audit["checks"].values()) and len(audit["checks"]) > 10
    assert audit["before"]["bar_1d"] == (5, 3) and audit["after_old"]["bar_1d"][0] == 3
    assert state(conn) == before  # not one row changed


def test_applying_splits_the_history_at_the_change_and_the_issuer_read_is_unchanged(issuer):
    conn, iid = issuer
    rd = BarReader(conn)
    modes = ("none", "split", "total_return")

    def read(read_fn, mode):
        return [(b.close, b.factor, b.volume) for b in read_fn(FIRST, LAST, adjust=mode).bars]

    today = {m: read(lambda s, e, adjust: rd.history(iid, s, e, adjust=adjust), m) for m in modes}
    audit = migrate_isin_change(conn, new_id=iid, dry_run=False, **KW)
    old = audit["old_instrument_id"]
    assert audit["applied"] is True and old != iid
    assert len(rd.history(iid, FIRST, LAST).bars) == 2  # the instruments stay apart
    assert len(rd.history(old, FIRST, LAST).bars) == 3
    for mode, want in today.items():  # the issuer series is exactly what it was
        assert read(lambda s, e, adjust: rd.issuer_history(iid, s, e, adjust=adjust), mode) == want

    def one(sql, *a):
        return conn.execute(sql, a).fetchone()

    assert one(
        "SELECT valid_from, valid_from_basis FROM instrument_alias WHERE instrument_id=%s", iid
    ) == (CHANGE, "EVIDENCED")
    assert one("SELECT valid_from, valid_to, valid_from_basis, valid_to_basis FROM instrument_alias WHERE instrument_id=%s", old) == (date(2010, 1, 8), CHANGE, "FIRST_OBSERVED", "EVIDENCED")  # fmt: skip
    assert one("SELECT isin, status, listed_on, delisted_on, last_traded_on FROM instrument WHERE instrument_id=%s", old) == ("INE239A01016", "delisted", None, CHANGE, date(2024, 1, 4))  # fmt: skip
    assert one("SELECT first_observed_on FROM instrument WHERE instrument_id=%s", iid)[0] == CHANGE
    assert one("SELECT valid_from, valid_to FROM instrument_terms WHERE instrument_id=%s", old) == (
        date(2023, 8, 1),
        CHANGE,
    )
    assert one("SELECT valid_from, valid_to FROM instrument_terms WHERE instrument_id=%s", iid) == (
        CHANGE,
        None,
    )
    rel = conn.execute(
        "SELECT relationship_type, source_instrument_id, target_instrument_id, effective_date,"
        " last_source_session, review_decision_id FROM corporate_action_relationship"
    ).fetchall()
    assert rel == [("SAME_ISSUER_ISIN_CHANGE", old, iid, CHANGE, date(2024, 1, 4), 15)]


def test_applying_twice_is_a_no_op(issuer):
    conn, iid = issuer
    migrate_isin_change(conn, new_id=iid, dry_run=False, **KW)
    after_first = state(conn)
    again = migrate_isin_change(conn, new_id=iid, dry_run=False, **KW)
    assert again == {"applied": False, "already_applied": True, "instrument_id": iid}
    assert state(conn) == after_first


def test_unsafe_requests_are_refused_before_anything_changes(issuer):
    conn, iid = issuer
    before = state(conn)
    with pytest.raises(MigrationError, match="does not exist"):
        migrate_isin_change(conn, new_id=999, **KW)
    with pytest.raises(MigrationError, match="same"):
        migrate_isin_change(conn, new_id=iid, **{**KW, "old_isin": "INE239A01024"})
    with pytest.raises(MigrationError, match="needs bars on both sides"):
        migrate_isin_change(conn, new_id=iid, **{**KW, "change": date(2024, 6, 1)})
    with pytest.raises(MigrationError, match="needs bars on both sides"):
        migrate_isin_change(conn, new_id=iid, **{**KW, "change": date(2023, 1, 1)})
    assert state(conn) == before
    conn.execute(
        "INSERT INTO instrument (asset_class, exchange_id, symbol, isin, quote_currency)"
        " SELECT 'equity', exchange_id, 'ZZ', 'INE239A01016', 'INR' FROM instrument LIMIT 1"
    )
    with pytest.raises(MigrationError, match="already exists"):
        migrate_isin_change(conn, new_id=iid, **KW)


def test_a_failed_post_check_rolls_the_whole_migration_back(issuer, monkeypatch):
    conn, iid = issuer
    before = state(conn)
    real = BarReader.issuer_load

    def tampered(self, instrument_id, *, strict=False):
        loaded = real(self, instrument_id, strict=strict)
        loaded.rows = [(*r[:4], r[4] + 1, r[5]) for r in loaded.rows]  # the read after differs
        return loaded

    monkeypatch.setattr(BarReader, "issuer_load", tampered)
    with pytest.raises(MigrationError, match="post-checks failed, rolled back"):
        migrate_isin_change(conn, new_id=iid, dry_run=False, **KW)
    monkeypatch.undo()
    assert state(conn) == before
