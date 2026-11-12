import copy
import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.backtest.costs.schedule import (
    NoScheduleForDate,
    ScheduleBook,
    ScheduleError,
    load_schedules,
    schedule_from_dict,
)

CFG = Path(__file__).parents[4] / "config/cost_schedules"
RAW = json.loads((CFG / "nse_cash_zerodha.json").read_text())["schedules"][0]  # delivery


def doc(**changes):
    d = copy.deepcopy(RAW)
    d.update(changes)
    return d


def err(d, match):
    with pytest.raises(ScheduleError, match=match):
        schedule_from_dict(d)


# ---- the committed data --------------------------------------------------------------------
def test_committed_files_load_and_every_component_cites_a_real_source():
    schedules = load_schedules(CFG)
    assert (
        len(schedules) == 10
    )  # delivery: 7 dated history periods + current; intraday: assumed + current
    for s in schedules:
        pre_gst = s.valid_until is not None and s.valid_until < date(
            2017, 7, 1
        )  # no GST existed yet
        assert s.product in ("DELIVERY", "INTRADAY") and (s.components[-1].type == "GST") != pre_gst
        for c in s.components:
            src = s.sources[c.source]
            assert len(src.sha256) == 64 and src.url.startswith("https://") and src.quote
        assert s.doc_hash and s.currency == "INR"


def test_current_rates_are_unverified_and_the_backfill_is_flagged_as_assumed():
    by_id = {s.id: s for s in load_schedules(CFG)}
    cur = by_id["nse-cash-delivery-zerodha-2026-03-01"]
    assert (cur.status, cur.valid_from, cur.valid_until) == (
        "extracted_unverified",
        date(2026, 3, 1),
        None,
    )
    assert cur.verified_by is None and cur.verified_at is None
    old = by_id["nse-cash-intraday-zerodha-assumed-2020-07-01"]
    assert old.status == "assumed_backfill" and old.valid_until == date(2026, 2, 28)
    assert "NOT evidenced" in old.notes and cur.contract_note_min_brokerage == D("0.01")
    early = by_id["nse-cash-delivery-zerodha-2017-07-01"]
    assert early.status == "assumed_backfill" and "NOT from a stored document" in early.notes


def test_a_pattern_selects_files_and_a_single_document_file_is_accepted(tmp_path):
    (tmp_path / "one.json").write_text(
        json.dumps(RAW)
    )  # a bare schedule, not wrapped in {"schedules": []}
    assert [s.id for s in load_schedules(tmp_path)] == [RAW["id"]]
    assert load_schedules(tmp_path, pattern="nothing*.json") == []


def test_the_content_hash_changes_with_any_rate():
    a = schedule_from_dict(RAW)
    d = doc()
    d["components"][1]["rate_pct"] = "0.11"
    assert (
        schedule_from_dict(d).doc_hash != a.doc_hash
        and schedule_from_dict(RAW).doc_hash == a.doc_hash
    )


# ---- strict validation -----------------------------------------------------------------------
def test_a_valid_document_loads_with_decimals():
    s = schedule_from_dict(RAW)
    stt = next(c for c in s.components if c.type == "STT")
    assert (
        stt.rate_pct == D("0.1") and s.covers(date(2026, 3, 1)) and not s.covers(date(2026, 2, 28))
    )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("status", "trusted", "unknown status"),
        ("product", "SWING", "unknown product"),
        ("valid_from", "2026/03/01", "not an ISO date"),
        ("valid_from", None, "bad validity range"),
        ("valid_until", "2026-01-01", "bad validity range"),
        ("components", [], "no components"),
        ("name", "", "missing name"),
        ("id", "", "missing id"),
    ],
)
def test_bad_top_level_fields_are_rejected(field, value, match):
    err(doc(**{field: value}), match)


def test_verified_needs_a_named_verifier_and_a_time():
    err(doc(status="verified"), "verified needs verified_by and verified_at")
    err(doc(status="verified", verified_by="ilesh"), "verified needs verified_by and verified_at")
    ok = schedule_from_dict(
        doc(status="verified", verified_by="ilesh", verified_at="2026-11-08T10:00:00+00:00")
    )
    assert ok.status == "verified" and ok.verified_by == "ilesh" and ok.verified_at.year == 2026


def mutate(index, **changes):
    d = doc()
    d["components"][index].update(changes)
    return d


@pytest.mark.parametrize(
    ("index", "changes", "match"),
    [
        (0, {"type": "TIPS"}, "unknown component type"),
        (0, {"basis": "PER_MOON"}, "bad basis/side"),
        (0, {"side": "NEITHER"}, "bad basis/side"),
        (0, {"rounding": "TRUNCATE"}, "unknown rounding"),
        (0, {"source": "made_up"}, "cites unknown source"),
        (0, {"rate_pct": "-1"}, "needs rate_pct >= 0"),
        (0, {"rate_pct": None}, "needs rate_pct >= 0"),
        (5, {"amount": None}, "needs amount >= 0"),
        (5, {"amount": "-2"}, "needs amount >= 0"),
        (0, {"minimum": "-1"}, "minimum cannot be negative"),
        (0, {"maximum": "-1"}, "maximum cannot be negative"),
        (0, {"minimum": "10", "maximum": "5"}, "minimum above maximum"),
        (0, {"taxable_for_gst": True, "gst_inclusive": True}, "both GST-taxable and GST-inclusive"),
        (6, {"type": "STT"}, "GST must be the .only. GST_BASE component"),
        (0, {"rate_pct": "abc"}, "not a number"),
    ],
)
def test_bad_components_are_rejected(index, changes, match):
    err(mutate(index, **changes), match)


def test_gst_must_be_unique_and_last():
    d = doc()
    d["components"].append(copy.deepcopy(d["components"][-1]))
    err(d, "more than one GST component")
    d2 = doc()
    d2["components"].insert(0, d2["components"].pop())  # GST first
    err(d2, "GST must be the last component")


@pytest.mark.parametrize("missing", ["url", "retrieved_at", "sha256", "quote"])
def test_every_source_needs_its_evidence_fields(missing):
    d = doc()
    first = next(iter(d["sources"]))
    d["sources"][first][missing] = ""
    err(d, f"source '{first}' is missing {missing}")


# ---- the book picks the schedule in force on the trade date ---------------------------------
def test_strict_use_refuses_unverified_rates():
    book = ScheduleBook(load_schedules(CFG))  # default: verified only
    with pytest.raises(
        NoScheduleForDate,
        match="no DELIVERY cost schedule .statuses allowed: verified. covers 2026-06-01",
    ):
        book.for_date(date(2026, 6, 1))
    assert book.coverage() == []


def test_research_use_accepts_extracted_rates_and_the_dates_are_inclusive():
    book = ScheduleBook(load_schedules(CFG), allowed_statuses=("extracted_unverified",))
    assert book.for_date(date(2026, 3, 1)).id == "nse-cash-delivery-zerodha-2026-03-01"
    assert book.for_date(date(2030, 1, 1), "INTRADAY").product == "INTRADAY"  # open-ended
    with pytest.raises(NoScheduleForDate):
        book.for_date(date(2026, 2, 28), "INTRADAY")  # the day before it starts: no guessing
    with pytest.raises(NoScheduleForDate):
        book.for_date(date(2022, 7, 17))  # delivery: the day before the first evidenced period


def test_the_assumed_backfill_is_opt_in_and_its_boundaries_are_exact():
    everything = ("extracted_unverified", "assumed_backfill")
    book = ScheduleBook(load_schedules(CFG), allowed_statuses=everything)
    assert book.for_date(date(2020, 7, 1), "INTRADAY").status == "assumed_backfill"
    assert book.for_date(date(2026, 2, 28), "INTRADAY").status == "assumed_backfill"
    assert book.for_date(date(2026, 3, 1), "INTRADAY").status == "extracted_unverified"
    with pytest.raises(NoScheduleForDate):
        book.for_date(
            date(2020, 6, 30), "INTRADAY"
        )  # intraday stamp duty regime differs before 1 July 2020
    assert book.coverage("INTRADAY") == [
        (date(2020, 7, 1), date(2026, 2, 28)),
        (date(2026, 3, 1), None),
    ]


def test_overlapping_schedules_for_the_same_product_are_refused():
    a = schedule_from_dict(doc(valid_from="2026-01-01", valid_until="2026-06-30", id="a"))
    b = schedule_from_dict(doc(valid_from="2026-06-30", valid_until=None, id="b"))
    with pytest.raises(ScheduleError, match="schedules a and b overlap for DELIVERY"):
        ScheduleBook([a, b], allowed_statuses=("extracted_unverified",))
    open_ended = schedule_from_dict(doc(valid_from="2026-01-01", valid_until=None, id="a"))
    with pytest.raises(ScheduleError, match="overlap"):
        ScheduleBook([open_ended, b], allowed_statuses=("extracted_unverified",))
    c = schedule_from_dict(doc(valid_from="2026-07-01", valid_until=None, id="c"))
    assert len(ScheduleBook([a, c], allowed_statuses=("extracted_unverified",)).schedules) == 2


# ---- gaps found by mutation testing ------------------------------------------------------------
def minimal_component(**changes):
    d = doc()
    base = {
        k: d["components"][1][k]
        for k in ("type", "basis", "side", "rate_pct", "rounding", "source")
    }
    d["components"][1] = {**base, **changes}  # no taxable_for_gst / gst_inclusive keys at all
    return d


def test_a_component_that_does_not_mention_gst_is_not_taxable_and_not_inclusive():
    """The dangerous default: a forgotten flag must never silently make something GST-taxable."""
    s = schedule_from_dict(minimal_component())
    stt = s.components[1]
    assert stt.taxable_for_gst is False and stt.gst_inclusive is False


@pytest.mark.parametrize(
    ("missing", "match"),
    [
        ("type", "unknown component type ''"),
        ("rounding", "unknown rounding ''"),
        ("source", "cites unknown source ''"),
    ],
)
def test_missing_component_fields_are_reported_as_empty_not_none(missing, match):
    d = minimal_component()
    del d["components"][1][missing]
    err(d, match)


def test_a_document_without_an_id_is_reported_under_a_placeholder_name():
    d = doc()
    del d["id"]
    err(d, "^<schedule>: missing id$")


@pytest.mark.parametrize("field", ["rate_pct", "minimum", "maximum"])
def test_a_non_numeric_value_names_the_field(field):
    d = doc()
    d["components"][0][field] = "abc"
    err(d, rf"components\[0\]\.{field}: not a number: 'abc'")


def test_a_non_numeric_flat_amount_names_the_field():
    d = doc()
    d["components"][5]["amount"] = "abc"
    err(d, r"components\[5\]\.amount: not a number: 'abc'")


def test_zero_is_a_valid_flat_amount_minimum_and_maximum_and_min_may_equal_max():
    d = doc()
    d["components"][5]["amount"] = "0"
    d["components"][0]["minimum"], d["components"][0]["maximum"] = "0", "0"
    d["components"][1]["minimum"], d["components"][1]["maximum"] = "5", "5"
    s = schedule_from_dict(d)
    assert (
        s.components[5].amount == 0
        and s.components[0].maximum == 0
        and s.components[1].minimum == 5
    )


def test_the_contract_note_minimum_may_be_absent():
    d = doc()
    del d["contract_note_min_brokerage"]
    assert schedule_from_dict(d).contract_note_min_brokerage is None
