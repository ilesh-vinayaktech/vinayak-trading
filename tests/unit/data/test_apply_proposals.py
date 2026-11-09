# ruff: noqa: E501
from datetime import date

from algo.data.apply_proposals import (
    dry_run,
    membership_proposal,
    parse_facts,
    symbol_proposal,
)

D = date
REC = {"decision_id": 7, "reviewer": "r", "evidence_ref": "doc"}


def rec(decision, effective=None):
    return {**REC, "decision": decision, "effective_date": effective}


FACTS = {"first": D(2006, 2, 16), "last": D(2026, 5, 11), "isin": "INE246F01010"}
NONE = {"instrument": None, "aliases": []}


def test_facts_come_from_the_items_own_context():
    ctx = {
        "Exchange files": "2006-02-16 .. 2026-05-11 (3375 legacy)",
        "ISINs seen": "INE246F01010[2011..]",
    }
    assert parse_facts(ctx) == FACTS
    assert parse_facts({"Exchange files": "- .. - (0 legacy)", "ISINs seen": None}) == {
        "first": None,
        "last": None,
        "isin": None,
    }
    assert parse_facts({}) == {"first": None, "last": None, "isin": None}


def test_a_placeholder_gets_no_instrument_and_no_alias():
    p = symbol_proposal(
        "DUMMYX", rec("KEEP_PLACEHOLDER"), {"first": None, "last": None, "isin": None}, NONE
    )
    assert p["kind"] == "PLACEHOLDER" and p["actions"] == [] and p["status"] == "PROPOSED"
    assert p["evidence"][0] == "doc" and p["decision_id"] == 7


def test_a_merged_security_is_its_own_instrument_with_a_typed_dated_relationship_not_an_alias():
    p = symbol_proposal("GSPL", rec("KEEP_SEPARATE"), FACTS, NONE)
    assert p["kind"] == "HISTORICAL_INSTRUMENT" and p["status"] == "PROPOSED"
    inst, alias, relation = p["actions"]
    # an archive boundary is never a listing date, and no delisting date is invented
    assert inst["values"] == {"symbol": "GSPL", "isin": "INE246F01010", "status": "delisted", "listed_on": None,
                              "first_observed_on": D(2006, 2, 16), "last_traded_on": D(2026, 5, 11),
                              "delisted_on": None}  # fmt: skip
    assert alias["values"] == {"instrument_id": "<new>", "source": "nse", "source_symbol": "GSPL",
                               "valid_from": D(2006, 2, 16), "valid_from_basis": "FIRST_OBSERVED",
                               "valid_to": D(2026, 5, 12), "valid_to_basis": "LAST_OBSERVED"}  # fmt: skip
    v = relation["values"]
    assert relation["table"] == "corporate_action_relationship"
    assert (v["relationship_type"], v["target_symbol"], v["effective_date"]) == (
        "AMALGAMATED_INTO",
        "GUJENERGY",
        D(2026, 5, 1),
    )
    assert (v["ratio_num"], v["ratio_den"], v["known_at"], v["verification_status"]) == (
        10,
        13,
        None,
        "PROVISIONAL",
    )
    assert (
        v["review_decision_id"] == 7 and v["source_instrument_id"] == "<new>" and "alias" not in v
    )


def test_a_stated_delisting_date_is_kept_but_an_archive_end_is_not_one():
    p = symbol_proposal(
        "HEXAWARE", rec("NO_SUCCESSOR", D(2020, 10, 30)), FACTS | {"isin": "INE093A01033"}, NONE
    )
    assert p["actions"][0]["values"]["delisted_on"] == D(
        2020, 11, 9
    )  # NSE delisting date, per the delisting FAQ
    relation = p["actions"][-1]["values"]
    assert (
        relation["relationship_type"] == "SAME_ISSUER_NEW_INSTRUMENT"
        and relation["target_symbol"] == "HEXT"
    )
    assert (
        relation["ratio_num"] is None and relation["ratio_den"] is None
    )  # a relisting has no exchange ratio


def test_an_existing_instrument_is_completed_not_duplicated():
    inst = {"id": 2642, "isin": None}
    p = symbol_proposal(
        "MINDTREE",
        rec("NO_SUCCESSOR"),
        FACTS | {"isin": "INE018I01017"},
        {"instrument": inst, "aliases": []},
    )
    assert p["kind"] == "COMPLETE_EXISTING_INSTRUMENT"
    assert [(a["table"], a["operation"]) for a in p["actions"]] == [
        ("instrument", "UPDATE"),
        ("instrument_alias", "INSERT"),
        ("corporate_action_relationship", "INSERT"),
    ]
    assert p["actions"][-1]["values"]["source_instrument_id"] == 2642
    done = {
        "instrument": {"id": 1, "isin": "INE018I01017"},
        "aliases": [(D(2018, 4, 2), D(2022, 11, 23))],
    }
    q = symbol_proposal("UNKNOWNCO", rec("KEEP_SEPARATE"), FACTS, done)
    assert q["kind"] == "NO_CHANGE_NEEDED" and q["actions"] == []
    r = symbol_proposal(
        "MINDTREE",
        rec("KEEP_SEPARATE"),
        FACTS | {"isin": None},
        {"instrument": {"id": 2, "isin": None}, "aliases": [(D(2018, 4, 2), None)]},
    )
    assert [a["table"] for a in r["actions"]] == [
        "corporate_action_relationship"
    ]  # no ISIN seen, alias present


def test_a_confirmed_mapping_is_an_alias_unless_it_is_already_there():
    inst = {"id": 2632, "isin": None}
    new = symbol_proposal(
        "DHANI",
        rec("CONFIRM_MAPPING", D(2020, 10, 28)),
        FACTS,
        {"instrument": inst, "aliases": [(D(2017, 9, 29), D(2020, 10, 28))]},
    )
    v = new["actions"][0]["values"]
    assert new["kind"] == "SYMBOL_ALIAS" and (v["valid_from"], v["valid_from_basis"]) == (
        D(2020, 10, 28),
        "EVIDENCED",
    )
    assert (v["valid_to"], v["valid_to_basis"]) == (D(2026, 5, 12), "LAST_OBSERVED")
    have = symbol_proposal(
        "DHANI",
        rec("CONFIRM_MAPPING", D(2020, 10, 28)),
        FACTS,
        {"instrument": inst, "aliases": [(D(2020, 10, 28), D(2025, 10, 28))]},
    )
    assert have["kind"] == "ALIAS_ALREADY_PRESENT" and have["actions"] == []
    open_end = symbol_proposal(
        "DHANI",
        rec("CONFIRM_MAPPING", D(2020, 10, 28)),
        {"first": None, "last": None, "isin": None},
        {"instrument": inst, "aliases": []},
    )
    assert (
        open_end["actions"][0]["values"]["valid_to"] is None
        and open_end["actions"][0]["values"]["valid_to_basis"] is None
    )


def test_an_isin_change_is_blocked_until_the_overlap_and_its_dependents_are_resolved():
    live = {"instrument": {"id": 1589, "isin": "INE239A01024"}, "aliases": [(D(2023, 8, 1), None)],
            "dependents": {"bar_1d": (811, 107), "corporate_action": (60, 55), "index_release_row": (63, 40)}}  # fmt: skip
    p = symbol_proposal(
        "NESTLEIND",
        rec("SET_EFFECTIVE_DATE", D(2024, 1, 5)),
        FACTS | {"isin": "INE239A01016"},
        live,
    )
    assert p["status"] == "BLOCKED" and p["kind"] == "BLOCKED_IDENTITY_MODEL" and p["actions"] == []
    assert "107 bars before 2024-01-05" in p["caveats"][0] and "63 release rows" in p["caveats"][0]
    assert any("overlap" in c for c in p["caveats"]) and any(
        "MOVE bars" in x for x in p["plan_if_approved"]
    )
    assert any("2024-01-05" in x for x in p["plan_if_approved"])
    bare = symbol_proposal(
        "NESTLEIND",
        rec("SET_EFFECTIVE_DATE", D(2024, 1, 5)),
        FACTS,
        {"instrument": {"id": 1}, "aliases": []},
    )
    assert "0 bars before" in bare["caveats"][0]


def test_a_membership_decision_writes_nothing():
    p = membership_proposal(
        "membership:X", rec("PARSER_ERROR"), ["config/revocations/a.json"], False
    )
    assert (
        p["actions"] == []
        and p["kind"] == "NO_WRITE_REFLECTED_IN_RECONSTRUCTION"
        and p["caveats"] == []
    )
    assert membership_proposal("membership:X", rec("PARSER_ERROR"), ["c"], True)["caveats"]


def test_the_dry_run_clears_only_what_the_proposed_alias_fully_covers():
    prop = [{"actions": [
        {"table": "instrument_alias", "operation": "INSERT", "values": {"source_symbol": "GSPL", "valid_from": D(2006, 2, 16), "valid_to": D(2026, 5, 12)}},
        {"table": "instrument_alias", "operation": "INSERT", "values": {"source_symbol": "PEL", "valid_from": D(2012, 9, 21), "valid_to": D(2022, 1, 1)}},
        {"table": "instrument", "operation": "INSERT", "values": {}},
        {"table": "instrument_alias", "operation": "INSERT", "values": {"source_symbol": "OPEN", "valid_from": D(2020, 1, 1), "valid_to": None}},
    ]}]  # fmt: skip
    exc = [
        {"kind": "MEMBER_WITHOUT_INSTRUMENT", "entity": e}
        for e in ("s:GSPL", "s:PEL", "s:JIOFIN", "s:OPEN")
    ]
    exc.append({"kind": "PLACEHOLDER_NOT_TRADABLE", "entity": "p:DUMMYX"})
    iv = [{"entity": "s:GSPL", "start": "2020-10-01", "end_exclusive": "2023-03-31"},
          {"entity": "s:PEL", "start": "2020-10-01", "end_exclusive": "2022-08-08"},
          {"entity": "s:JIOFIN", "start": "2023-07-20", "end_exclusive": "2023-08-21"},
          {"entity": "s:OPEN", "start": "2021-01-01", "end_exclusive": ""}]  # fmt: skip
    out = {r["entity"]: r for r in dry_run(exc, iv, prop, D(2026, 11, 7))}
    assert [r["result"] for r in out.values()] == ["CLEARED", "REMAINS", "REMAINS", "CLEARED"]
    assert (
        "does not cover" in out["s:PEL"]["reason"] and "non-tradable" in out["s:JIOFIN"]["reason"]
    )
    assert "p:DUMMYX" not in out
