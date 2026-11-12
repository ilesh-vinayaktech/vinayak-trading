import json
from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.backtest.costs.calculator import compute_charges
from algo.backtest.costs.schedule import NoScheduleForDate, ScheduleError
from algo.backtest.costs.schedule_store import (
    add,
    add_provider,
    add_version,
    backfill,
    get,
    import_files,
    list_schedules,
    load_book,
    remove,
    verify,
)
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
CONFIG = (
    Path(__file__).resolve().parents[1] / "fixtures/cost_schedules"
)  # a frozen copy: these tests exercise mechanics, not today's rates
NOW = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
ALL = ("verified", "extracted_unverified", "assumed_backfill")
CUR, OLD = "nse-cash-delivery-zerodha-2026-03-01", "nse-cash-delivery-zerodha-assumed-2020-07-01"
VERSION = "2026-11-07.1"


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


@pytest.fixture
def seeded(db):
    import_files(db, CONFIG, now=NOW)
    return db


def raw_docs():
    out = {}
    for f in sorted(CONFIG.glob("*.json")):
        doc = json.loads(f.read_text())
        for d in doc["schedules"] if "schedules" in doc else [doc]:
            out[d["id"]] = d
    return out


def test_the_schedules_in_the_config_folder_are_imported_once(db):
    assert import_files(db, CONFIG, now=NOW) == 4
    assert import_files(db, CONFIG, now=NOW) == 0  # the same documents again change nothing
    rows = list_schedules(db)
    assert {(r["schedule_id"], r["status"]) for r in rows} == {
        (CUR, "extracted_unverified"),
        (OLD, "assumed_backfill"),
        ("nse-cash-intraday-zerodha-2026-03-01", "extracted_unverified"),
        ("nse-cash-intraday-zerodha-assumed-2020-07-01", "assumed_backfill"),
    }
    cur = next(r for r in rows if r["schedule_id"] == CUR)
    assert (cur["broker"], cur["product"], cur["valid_from"], cur["valid_until"]) == (
        "zerodha",
        "DELIVERY",
        date(2026, 3, 1),
        None,
    )
    kinds = {
        "BROKERAGE",
        "STT",
        "EXCHANGE_TRANSACTION",
        "SEBI_TURNOVER",
        "STAMP_DUTY",
        "DP_CHARGE",
        "GST",
    }
    assert {c["type"] for c in cur["components"]} == kinds
    assert cur["sources"] and all(s["url"] and s["quote"] for s in cur["sources"])


def test_a_changed_document_under_the_same_id_is_refused_not_overwritten(db):
    import_files(db, CONFIG, now=NOW)
    doc = {**raw_docs()[CUR], "notes": "edited"}
    with pytest.raises(ScheduleError, match="different"):
        add(db, doc, actor=None, now=NOW)


def test_the_book_picks_the_schedule_in_force_among_the_statuses_a_run_allows(seeded):
    book = load_book(seeded, "zerodha", allowed_statuses=ALL)
    assert book.for_date(date(2023, 5, 2), "DELIVERY").id == OLD
    assert book.for_date(date(2026, 11, 12), "DELIVERY").id == CUR
    with pytest.raises(NoScheduleForDate):
        load_book(seeded, "zerodha").for_date(
            date(2026, 11, 12), "DELIVERY"
        )  # nothing is verified yet
    with pytest.raises(NoScheduleForDate):
        load_book(seeded, "unknown-broker", allowed_statuses=ALL).for_date(
            date(2026, 11, 12), "DELIVERY"
        )
    charges = compute_charges(book.for_date(date(2026, 11, 12), "DELIVERY"), "BUY", D(100), D(200))
    assert charges.schedule_status == "extracted_unverified" and charges.total > 0


def test_a_person_verifying_a_schedule_is_recorded_and_makes_it_usable_when_only_verified_is_allowed(
    seeded,
):
    sch = verify(seeded, CUR, VERSION, by="Ilesh Patel", now=NOW)
    assert (sch.status, sch.verified_by, sch.verified_at) == ("verified", "Ilesh Patel", NOW)
    assert get(seeded, CUR, VERSION).status == "verified"
    assert load_book(seeded, "zerodha").for_date(date(2026, 11, 12), "DELIVERY").id == CUR
    row = next(r for r in list_schedules(seeded) if r["schedule_id"] == CUR)
    assert (row["status"], row["verified_by"]) == ("verified", "Ilesh Patel")
    with pytest.raises(ScheduleError, match="already verified"):
        verify(seeded, CUR, VERSION, by="x", now=NOW)
    with pytest.raises(ScheduleError, match="assumed"):
        verify(seeded, OLD, VERSION, by="x", now=NOW)  # an assumption is not something to verify
    with pytest.raises(ScheduleError, match="no such schedule"):
        verify(seeded, "nope", VERSION, by="x", now=NOW)


def test_the_current_rates_can_be_extended_over_all_earlier_history_as_a_flagged_assumption(seeded):
    remove(
        seeded, OLD, VERSION
    )  # replace the old backfill (it started in July 2020) with one reaching back further
    sch = backfill(seeded, CUR, VERSION, valid_from=date(2016, 1, 1), actor=None, now=NOW)
    assert (sch.status, sch.valid_from, sch.valid_until) == (
        "assumed_backfill",
        date(2016, 1, 1),
        date(2026, 2, 28),
    )
    assert sch.id == f"{CUR}-backfill-2016-01-01" and sch.verified_by is None
    source = get(seeded, CUR, VERSION)
    assert [(c.type, c.rate_pct, c.amount) for c in sch.components] == [
        (c.type, c.rate_pct, c.amount) for c in source.components
    ]
    book = load_book(seeded, "zerodha", allowed_statuses=ALL)
    assert book.for_date(date(2017, 6, 1), "DELIVERY").id == sch.id
    assert book.for_date(date(2026, 3, 1), "DELIVERY").id == CUR
    with pytest.raises(ScheduleError, match="overlaps"):
        backfill(
            seeded, CUR, VERSION, valid_from=date(2010, 1, 1), actor=None, now=NOW
        )  # that range is taken now
    with pytest.raises(ScheduleError, match="before"):
        backfill(
            seeded, CUR, VERSION, valid_from=date(2026, 3, 1), actor=None, now=NOW
        )  # must start before it does


def test_a_new_version_can_be_added_but_not_if_it_is_invalid_or_overlaps_another(seeded):
    base = raw_docs()[CUR]
    nxt = {**base, "id": "nse-cash-delivery-zerodha-2027-04-01", "valid_from": "2027-04-01"}
    with pytest.raises(ScheduleError, match="overlaps"):
        add(seeded, nxt, actor=None, now=NOW)  # the 2026 one is open-ended
    seeded.execute(
        "UPDATE cost_schedule SET valid_until='2027-03-31', doc = jsonb_set(doc, '{valid_until}', '\"2027-03-31\"') WHERE schedule_id=%s",
        (CUR,),
    )
    added = add(seeded, nxt, actor=None, now=NOW)
    assert added.valid_from == date(2027, 4, 1)
    book = load_book(seeded, "zerodha", allowed_statuses=ALL)
    assert book.for_date(date(2027, 5, 1), "DELIVERY").id == added.id
    with pytest.raises(ScheduleError):
        add(seeded, {**base, "id": "x", "components": []}, actor=None, now=NOW)


def test_only_schedules_that_nobody_verified_can_be_removed(seeded):
    verify(seeded, CUR, VERSION, by="Ilesh Patel", now=NOW)
    with pytest.raises(ScheduleError, match="verified"):
        remove(seeded, CUR, VERSION)
    remove(seeded, OLD, VERSION)
    assert OLD not in {r["schedule_id"] for r in list_schedules(seeded)}
    with pytest.raises(ScheduleError, match="no such schedule"):
        remove(seeded, OLD, VERSION)


def test_adding_the_same_document_twice_is_a_no_op_and_a_missing_schedule_is_reported(seeded):
    again = add(seeded, raw_docs()[CUR], actor=None, now=NOW)
    assert again.id == CUR and len(list_schedules(seeded)) == 4
    with pytest.raises(ScheduleError, match="no such schedule"):
        get(seeded, "nope", VERSION)


def test_a_price_change_is_entered_as_a_new_version_with_its_own_start_date_and_the_old_one_ends_the_day_before(
    seeded,
):
    new = add_version(
        seeded, CUR, VERSION, valid_from=date(2027, 4, 1), valid_until=None,
        changes=[{"type": "STT", "side": "BOTH", "rate_pct": "0.11"}], note="Budget 2027 STT change", by="Ilesh Patel", actor=None, now=NOW,
    )  # fmt: skip
    assert (new.status, new.valid_from, new.valid_until, new.broker, new.product) == (
        "extracted_unverified",
        date(2027, 4, 1),
        None,
        "zerodha",
        "DELIVERY",
    )
    stt = next(c for c in new.components if c.type == "STT")
    assert stt.rate_pct == D("0.11") and stt.source == "owner_entered"
    assert (
        new.sources["owner_entered"].quote == "Budget 2027 STT change"
        and new.sources["owner_entered"].url == "owner-entered"
    )
    untouched = next(c for c in new.components if c.type == "BROKERAGE")
    assert (
        untouched.source
        == next(c for c in get(seeded, CUR, VERSION).components if c.type == "BROKERAGE").source
    )
    assert get(seeded, CUR, VERSION).valid_until == date(
        2027, 3, 31
    )  # the 2026 rates now end the day before
    book = load_book(seeded, "zerodha", allowed_statuses=ALL)
    assert book.for_date(date(2026, 12, 1), "DELIVERY").id == CUR
    assert book.for_date(date(2027, 5, 1), "DELIVERY").id == new.id
    assert (
        get(seeded, new.id, new.version).sources["owner_entered"].quote == "Budget 2027 STT change"
    )


def test_a_new_version_that_cannot_be_added_leaves_the_old_one_exactly_as_it_was(seeded):
    with pytest.raises(ScheduleError, match="no such component"):
        add_version(
            seeded,
            CUR,
            VERSION,
            valid_from=date(2027, 4, 1),
            valid_until=None,
            changes=[{"type": "DP_CHARGE", "side": "BUY", "amount": "1"}],
            note="n",
            by="x",
            actor=None,
            now=NOW,
        )
    with pytest.raises(ScheduleError, match="before"):
        add_version(
            seeded,
            CUR,
            VERSION,
            valid_from=date(2026, 1, 1),
            valid_until=None,
            changes=[{"type": "STT", "side": "BOTH", "rate_pct": "0.2"}],
            note="n",
            by="x",
            actor=None,
            now=NOW,
        )
    with pytest.raises(ScheduleError, match="rate"):
        add_version(
            seeded,
            CUR,
            VERSION,
            valid_from=date(2027, 4, 1),
            valid_until=None,
            changes=[{"type": "STT", "side": "BOTH", "rate_pct": "-1"}],
            note="n",
            by="x",
            actor=None,
            now=NOW,
        )
    assert get(seeded, CUR, VERSION).valid_until is None  # still open-ended: nothing was closed
    first = dict(
        valid_from=date(2027, 4, 1),
        valid_until=None,
        changes=[{"type": "STT", "side": "BOTH", "rate_pct": "0.11"}],
        note="n",
        by="x",
        actor=None,
        now=NOW,
    )
    one = add_version(seeded, CUR, VERSION, **first)
    assert (
        add_version(seeded, CUR, VERSION, **first).id == one.id
    )  # repeating the same entry is harmless
    other = {**first, "changes": [{"type": "STT", "side": "BOTH", "rate_pct": "0.12"}]}
    with pytest.raises(ScheduleError, match="different"):
        add_version(
            seeded, CUR, VERSION, **other
        )  # another rate for the same start date is a conflict


def test_a_new_provider_starts_as_an_unverified_copy_of_another_providers_current_rates(seeded):
    made = add_provider(
        seeded,
        "Angel One",
        template_broker="zerodha",
        valid_from=date(2026, 1, 1),
        note="rates to be entered",
        by="Ilesh Patel",
        actor=None,
        now=NOW,
    )
    assert sorted((s.product, s.broker, s.status, s.valid_from, s.valid_until) for s in made) == [
        ("DELIVERY", "angel-one", "extracted_unverified", date(2026, 1, 1), None),
        ("INTRADAY", "angel-one", "extracted_unverified", date(2026, 1, 1), None),
    ]
    delivery = next(s for s in made if s.product == "DELIVERY")
    template = get(seeded, CUR, VERSION)
    assert [(c.type, c.rate_pct, c.amount) for c in delivery.components] == [
        (c.type, c.rate_pct, c.amount) for c in template.components
    ]
    assert {c.source for c in delivery.components} == {
        "owner_entered"
    }  # nothing cites Zerodha's pages for another broker
    assert (
        set(delivery.sources) == {"owner_entered"}
        and "rates to be entered" in delivery.sources["owner_entered"].quote
    )
    assert (
        load_book(seeded, "angel-one", allowed_statuses=ALL)
        .for_date(date(2026, 6, 1), "INTRADAY")
        .id
        == "angel-one-intraday-2026-01-01"
    )
    assert {r["broker"] for r in list_schedules(seeded)} == {"zerodha", "angel-one"}


def test_a_provider_cannot_be_added_twice_or_from_a_template_that_does_not_exist(seeded):
    kw = dict(valid_from=date(2026, 1, 1), note="n", by="x", actor=None, now=NOW)
    with pytest.raises(ScheduleError, match="already exists"):
        add_provider(seeded, "Zerodha", template_broker="zerodha", **kw)
    with pytest.raises(ScheduleError, match="no schedule in force"):
        add_provider(seeded, "Groww", template_broker="nobody", **kw)
    with pytest.raises(ScheduleError, match="name"):
        add_provider(seeded, "  !!  ", template_broker="zerodha", **kw)
    assert {r["broker"] for r in list_schedules(seeded)} == {"zerodha"}  # nothing half-made
