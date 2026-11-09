from datetime import date

import psycopg
import pytest

from tests.support.bt import NOW, make_env

pytestmark = pytest.mark.integration


def inst(conn, symbol):
    return conn.execute(
        "INSERT INTO instrument (asset_class, exchange_id, symbol, quote_currency)"
        " VALUES ('equity', (SELECT exchange_id FROM exchange LIMIT 1), %s, 'INR') RETURNING instrument_id",
        (symbol,),
    ).fetchone()[0]


def alias(conn, iid, sym, lo, hi=None, **kw):
    conn.execute(
        "INSERT INTO instrument_alias (instrument_id, source, source_symbol, valid_from, valid_to,"
        " valid_from_basis, valid_to_basis) VALUES (%s,'nse',%s,%s,%s,%s,%s)",
        (iid, sym, lo, hi, kw.get("fb", "EVIDENCED"), kw.get("tb")),
    )


def rel(conn, a, b, **kw):
    vals = {"type": "AMALGAMATED_INTO", "tgt": b, "eff": date(2025, 9, 16), "ev": '["doc"]', "num": None, "den": None,
            "appointed": None, **kw}  # fmt: skip
    conn.execute(
        "INSERT INTO corporate_action_relationship (relationship_type, source_instrument_id, target_instrument_id,"
        " target_symbol, appointed_date, effective_date, ratio_num, ratio_den, evidence, review_decision_id,"
        " recorded_at) VALUES (%s,%s,%s,'T',%s,%s,%s,%s,%s::jsonb,1,%s)",
        (
            vals["type"],
            a,
            vals["tgt"],
            vals["appointed"],
            vals["eff"],
            vals["num"],
            vals["den"],
            vals["ev"],
            NOW,
        ),
    )


@pytest.fixture
def db(conn):
    make_env(conn)
    return conn


def test_archive_boundaries_and_listing_dates_are_separate_columns(db):
    iid = inst(db, "X")
    db.execute(
        "UPDATE instrument SET first_observed_on='2010-01-08', last_traded_on='2024-01-04' WHERE instrument_id=%s",
        (iid,),
    )
    row = db.execute(
        "SELECT listed_on, first_observed_on, last_traded_on FROM instrument WHERE instrument_id=%s",
        (iid,),
    ).fetchone()
    assert row == (None, date(2010, 1, 8), date(2024, 1, 4))  # listed_on stays NULL until evidenced


def test_two_aliases_of_one_symbol_may_not_overlap_but_may_touch(db):
    a, b = inst(db, "OLD"), inst(db, "NEW")
    alias(
        db, a, "NESTLEIND", date(2010, 1, 8), date(2024, 1, 5), fb="FIRST_OBSERVED", tb="EVIDENCED"
    )
    alias(
        db, b, "NESTLEIND", date(2024, 1, 5)
    )  # end-exclusive: starting on the end date is allowed
    c = inst(db, "THIRD")
    with pytest.raises(psycopg.errors.ExclusionViolation):
        alias(db, c, "NESTLEIND", date(2023, 8, 1), date(2024, 2, 1))
    alias(db, c, "OTHER", date(2023, 8, 1))  # a different symbol is independent


def test_an_alias_end_basis_needs_an_end_and_bases_are_restricted(db):
    a = inst(db, "A")
    with pytest.raises(psycopg.errors.CheckViolation):
        alias(db, a, "S", date(2020, 1, 1), None, tb="EVIDENCED")
    with pytest.raises(psycopg.errors.CheckViolation):
        alias(db, a, "S", date(2020, 1, 1), date(2021, 1, 1), fb="GUESSED")
    seeded = {r[0] for r in db.execute("SELECT valid_from_basis FROM instrument_alias").fetchall()}
    assert seeded == {
        "LEGACY_UNSPECIFIED"
    }  # aliases that predate the basis column say so, never "EVIDENCED"


def test_a_relationship_is_effective_dated_typed_and_evidenced(db):
    a, b = inst(db, "PEL"), inst(db, "PIRAMALFIN")
    rel(db, a, b, num=1, den=1, appointed=date(2024, 4, 1))
    row = db.execute(
        "SELECT relationship_type, target_symbol, effective_date, verification_status FROM corporate_action_relationship"
    ).fetchone()
    assert row == ("AMALGAMATED_INTO", "T", date(2025, 9, 16), "PROVISIONAL")
    rel(
        db, a, None, type="SAME_ISSUER_NEW_INSTRUMENT", eff=date(2025, 2, 19)
    )  # target not in the master yet
    with pytest.raises(psycopg.errors.UniqueViolation):
        rel(db, a, b)  # same type, source, target symbol and effective date


def test_a_relationship_refuses_nonsense(db):
    a, b = inst(db, "A"), inst(db, "B")
    with pytest.raises(psycopg.errors.CheckViolation):
        rel(db, a, b, type="SUCCESSOR")
    with pytest.raises(psycopg.errors.CheckViolation):
        rel(db, a, b, num=1)  # a ratio needs both sides
    with pytest.raises(psycopg.errors.CheckViolation):
        rel(db, a, b, num=0, den=1)
    with pytest.raises(psycopg.errors.CheckViolation):
        rel(db, a, a)  # a security is not its own successor
    with pytest.raises(psycopg.errors.CheckViolation):
        rel(db, a, b, ev="[]")  # no evidence
    with pytest.raises(psycopg.errors.CheckViolation):
        rel(db, a, b, appointed=date(2026, 1, 1))  # appointed after effective
    assert db.execute("SELECT count(*) FROM corporate_action_relationship").fetchone()[0] == 0
