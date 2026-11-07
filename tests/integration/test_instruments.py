from datetime import date
from decimal import Decimal as D

import psycopg
import pytest

from algo.data.store.instruments import InstrumentRepo, NotFoundError
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
D1, D2, D3 = date(2024, 1, 1), date(2025, 1, 1), date(2026, 1, 1)


@pytest.fixture
def repo(conn):
    migrate(conn)
    return InstrumentRepo(conn)


@pytest.fixture
def nse_id(repo):
    return repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")


def test_terms_change_over_time(repo, nse_id):
    i = repo.add_instrument(nse_id, "NIFTY24JANFUT", "future", listed_on=D1)
    repo.add_terms(i, D1, D2, D("50"), D("0.05"), D("50"))
    repo.add_terms(i, D2, None, D("25"), D("0.05"), D("25"), D("1"), "m2")
    assert repo.terms_as_of(i, date(2024, 12, 31)).lot_size == D("50")
    t = repo.terms_as_of(i, D2)  # valid_to exclusive: boundary day uses the new terms
    assert (t.lot_size, t.margin_rule_version) == (D("25"), "m2")
    assert repo.terms_as_of(i, D3).lot_size == D("25")


def test_no_terms_before_first_validity(repo, nse_id):
    i = repo.add_instrument(nse_id, "X")
    repo.add_terms(i, D2, None, D("1"), D("0.05"), D("1"))
    with pytest.raises(NotFoundError):
        repo.terms_as_of(i, D1)


def test_overlapping_terms_rejected(repo, nse_id):
    i = repo.add_instrument(nse_id, "X")
    repo.add_terms(i, D1, D3, D("1"), D("0.05"), D("1"))
    with pytest.raises(psycopg.errors.ExclusionViolation):
        repo.add_terms(i, D2, None, D("2"), D("0.05"), D("2"))


def test_bad_terms_rejected(repo, nse_id):
    i = repo.add_instrument(nse_id, "X")
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.add_terms(i, D1, None, D("0"), D("0.05"), D("1"))
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.add_terms(i, D2, D1, D("1"), D("0.05"), D("1"))


def test_alias_rename_keeps_same_instrument(repo, nse_id):
    i = repo.add_instrument(nse_id, "ZOMATO", isin="INE758T01015")
    repo.add_alias(i, "kite", "ZOMATO", D1, D3, token="5097")
    repo.add_alias(i, "kite", "ETERNAL", D3)
    assert repo.resolve("kite", "ZOMATO", D2) == i
    assert repo.resolve("kite", "ETERNAL", D3) == i
    with pytest.raises(NotFoundError):
        repo.resolve("kite", "ETERNAL", D2)  # not yet valid
    with pytest.raises(NotFoundError):
        repo.resolve("kite", "ZOMATO", D3)  # no longer valid


def test_alias_symbol_reuse_by_other_instrument_rejected_while_valid(repo, nse_id):
    a, b = repo.add_instrument(nse_id, "A"), repo.add_instrument(nse_id, "B")
    repo.add_alias(a, "kite", "SYM", D1)
    with pytest.raises(psycopg.errors.ExclusionViolation):
        repo.add_alias(b, "kite", "SYM", D2)


def test_delist_keeps_row(repo, conn, nse_id):
    i = repo.add_instrument(nse_id, "GONE", listed_on=D1)
    repo.delist(i, D2)
    assert conn.execute(
        "SELECT status, delisted_on FROM instrument WHERE instrument_id=%s", (i,)
    ).fetchone() == ("delisted", D2)


def test_invalid_asset_class_and_dates(repo, nse_id):
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.add_instrument(nse_id, "X", "bond")
    i = repo.add_instrument(nse_id, "Y", listed_on=D2)
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.delist(i, D1)


def test_us_and_crypto_rows_need_no_schema_change(repo):
    us = repo.add_exchange("XNAS", "US", "America/New_York", "USD", "NASDAQ")
    cr = repo.add_exchange("BINA", "XX", "UTC", "USDT", "24x7")
    a = repo.add_instrument(us, "AAPL", quote_currency="USD")
    b = repo.add_instrument(cr, "BTCUSDT", "crypto_spot", quote_currency="USDT")
    repo.add_terms(b, D1, None, D("0.00001"), D("0.01"), D("0.00001"))
    assert repo.terms_as_of(b, D2).qty_step == D("0.00001") and a != b
