import json
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from algo.backtest.costs.schedule_store import import_files
from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
CONFIG = (
    Path(__file__).resolve().parents[2] / "fixtures/cost_schedules"
)  # a frozen copy: these tests exercise mechanics, not today's rates
CUR = "nse-cash-delivery-zerodha-2026-03-01"
OLD = "nse-cash-delivery-zerodha-assumed-2020-07-01"
VERSION = "2026-11-07.1"
BASE = f"/api/costs/schedules/{CUR}/{VERSION}"
PREVIEW = "broker=zerodha&product=DELIVERY&side=BUY&qty=100&price=2850.5"


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    import_files(conn, CONFIG, now=START)
    clock = SimClock(START)
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock


def admin(conn, app, clock):
    add_user(conn, clock, "ADMIN", "boss@example.com", name="The Boss")
    c = sign_in(app, "boss@example.com")
    enrol_second_factor(c, clock)
    return c


def viewer(conn, app, clock):
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    return sign_in(app, "viewer@example.com")


def audit_actions(conn):
    rows = conn.execute(
        "SELECT action FROM portal_audit WHERE action LIKE 'costs.%' ORDER BY audit_id"
    )
    return [r[0] for r in rows]


def test_anyone_signed_in_can_read_the_costs_but_only_an_administrator_can_change_them(env):
    conn, app, clock = env
    for role, email in (
        ("VIEWER", "v@example.com"),
        ("TRADER", "t@example.com"),
        ("OPERATOR", "o@example.com"),
    ):
        add_user(conn, clock, role, email)
    changes = [
        ("POST", f"{BASE}/verify", None),
        ("POST", f"{BASE}/backfill", {"valid_from": "2016-01-01"}),
        ("POST", f"{BASE}/new-version", {"valid_from": "2027-04-01", "changes": [], "note": "x"}),
        ("POST", f"/api/costs/schedules/{OLD}/{VERSION}/remove", None),
        (
            "POST",
            "/api/costs/providers",
            {"name": "Groww", "template_broker": "zerodha", "valid_from": "2026-01-01"},
        ),
    ]
    for email in ("v@example.com", "t@example.com", "o@example.com"):
        c = sign_in(app, email)
        if email.startswith("o@"):
            enrol_second_factor(
                c, clock
            )  # operators must use two-factor sign-in before the portal serves them
        assert c.get("/api/costs/schedules").status_code == 200
        for method, path, body in changes:
            assert c.request(method, path, json=body).status_code == 403, (email, path)
    assert TestClient(app).get("/api/costs/schedules").status_code == 401
    assert admin(conn, app, clock).get("/api/costs/schedules").status_code == 200


def test_the_list_shows_each_schedule_with_its_rates_sources_and_status(env):
    conn, app, clock = env
    rows = viewer(conn, app, clock).get("/api/costs/schedules").json()["schedules"]
    assert len(rows) == 4
    cur = next(r for r in rows if r["schedule_id"] == CUR)
    assert (cur["broker"], cur["product"], cur["valid_from"], cur["valid_until"], cur["status"], cur["verified_by"]) == (
        "zerodha", "DELIVERY", "2026-03-01", None, "extracted_unverified", None,
    )  # fmt: skip
    stt = next(c for c in cur["components"] if c["type"] == "STT")
    assert stt == {
        "type": "STT",
        "side": "BOTH",
        "basis": "TRADE_VALUE",
        "rate_pct": "0.1",
        "amount": None,
        "minimum": None,
        "maximum": None,
        "source": stt["source"],
    }
    assert any(
        s["key"] == stt["source"] and s["url"].startswith("https://") and s["quote"]
        for s in cur["sources"]
    )


def test_the_preview_itemises_what_a_trade_would_cost_and_says_which_schedule_it_used(env):
    conn, app, clock = env
    c = viewer(conn, app, clock)
    d = c.get(f"/api/costs/preview?{PREVIEW}&day=2026-11-12").json()
    assert (
        d["schedule"]["id"] == CUR
        and d["schedule"]["status"] == "extracted_unverified"
        and d["value"] == "285050"
    )
    assert {line["type"] for line in d["lines"]} >= {"STT", "STAMP_DUTY", "GST"} and all(
        line["formula"] for line in d["lines"]
    )
    assert D(d["total"]) == sum(D(line["amount"]) for line in d["lines"])
    old = c.get(f"/api/costs/preview?{PREVIEW}&day=2023-05-02").json()
    assert old["schedule"]["id"] == OLD and old["schedule"]["status"] == "assumed_backfill"
    assert (
        c.get(f"/api/costs/preview?{PREVIEW}&day=2010-01-01").status_code == 404
    )  # no schedule covers it
    assert (
        c.get(
            "/api/costs/preview?broker=zerodha&product=DELIVERY&side=HOLD&qty=1&price=1&day=2026-11-12"
        ).status_code
        == 400
    )
    assert (
        c.get(
            "/api/costs/preview?broker=zerodha&product=DELIVERY&side=BUY&qty=0&price=1&day=2026-11-12"
        ).status_code
        == 400
    )


def test_verifying_records_who_did_it_and_a_second_time_is_refused(env):
    conn, app, clock = env
    c = admin(conn, app, clock)
    assert c.post(f"{BASE}/verify").json() == {"ok": True}
    row = next(
        r for r in c.get("/api/costs/schedules").json()["schedules"] if r["schedule_id"] == CUR
    )
    assert (row["status"], row["verified_by"]) == ("verified", "The Boss") and row["verified_at"]
    assert c.post(f"{BASE}/verify").status_code == 400
    assert (
        c.post(f"/api/costs/schedules/{OLD}/{VERSION}/verify").status_code == 400
    )  # an assumption cannot be verified
    assert c.post(f"/api/costs/schedules/nope/{VERSION}/verify").status_code == 404
    assert audit_actions(conn) == ["costs.verified"]


def test_current_rates_can_be_extended_over_all_earlier_history_and_the_old_extension_replaced(env):
    conn, app, clock = env
    c = admin(conn, app, clock)
    assert (
        c.post(f"{BASE}/backfill", json={"valid_from": "2016-01-01"}).status_code == 400
    )  # the old extension is in the way
    assert c.post(f"/api/costs/schedules/{OLD}/{VERSION}/remove").json() == {"ok": True}
    assert c.post(f"{BASE}/backfill", json={"valid_from": "2016-01-01"}).json() == {"ok": True}
    rows = c.get("/api/costs/schedules").json()["schedules"]
    new = next(r for r in rows if r["schedule_id"] == f"{CUR}-backfill-2016-01-01")
    assert (new["status"], new["valid_from"], new["valid_until"]) == (
        "assumed_backfill",
        "2016-01-01",
        "2026-02-28",
    )
    d = c.get(
        "/api/costs/preview?broker=zerodha&product=DELIVERY&side=SELL&qty=10&price=100&day=2017-06-01"
    ).json()
    assert d["schedule"]["id"] == new["schedule_id"]
    assert c.post(f"{BASE}/backfill", json={"valid_from": "2030-01-01"}).status_code == 400
    assert c.post(f"{BASE}/backfill", json={"valid_from": "not a date"}).status_code == 422
    assert audit_actions(conn) == ["costs.removed", "costs.backfilled"]


def test_a_price_change_is_entered_with_its_effective_date_and_ends_the_old_rates(env):
    conn, app, clock = env
    c = admin(conn, app, clock)
    stt = {"type": "STT", "side": "BOTH", "rate_pct": "0.11"}
    body = {
        "valid_from": "2027-04-01",
        "valid_until": None,
        "note": "Budget 2027",
        "changes": [stt],
    }
    assert c.post(f"{BASE}/new-version", json=body).json() == {"ok": True}
    rows = {r["schedule_id"]: r for r in c.get("/api/costs/schedules").json()["schedules"]}
    new = rows["zerodha-delivery-2027-04-01"]
    assert (new["status"], new["valid_from"], new["valid_until"]) == (
        "extracted_unverified",
        "2027-04-01",
        None,
    )
    assert next(x for x in new["components"] if x["type"] == "STT")["rate_pct"] == "0.11"
    assert rows[CUR]["valid_until"] == "2027-03-31"
    bad = {**body, "changes": [{"type": "NOPE", "side": "BOTH", "rate_pct": "1"}]}
    assert c.post(f"{BASE}/new-version", json=bad).status_code == 400
    assert (
        c.post(f"{BASE}/new-version", json={**body, "valid_from": "2026-01-01"}).status_code == 400
    )
    assert audit_actions(conn) == ["costs.version_added"]


def test_a_verified_schedule_cannot_be_removed_and_a_missing_one_is_not_found(env):
    conn, app, clock = env
    c = admin(conn, app, clock)
    c.post(f"{BASE}/verify")
    assert c.post(f"{BASE}/remove").status_code == 400
    assert c.post(f"/api/costs/schedules/nope/{VERSION}/remove").status_code == 404


def test_a_provider_is_added_as_an_unverified_copy_and_appears_with_its_own_schedules(env):
    conn, app, clock = env
    c = admin(conn, app, clock)
    body = {
        "name": "Groww",
        "template_broker": "zerodha",
        "valid_from": "2026-01-01",
        "note": "to be filled in",
    }
    assert c.post("/api/costs/providers", json=body).json() == {"ok": True}
    rows = [r for r in c.get("/api/costs/schedules").json()["schedules"] if r["broker"] == "groww"]
    assert sorted((r["product"], r["status"], r["valid_from"]) for r in rows) == [
        ("DELIVERY", "extracted_unverified", "2026-01-01"),
        ("INTRADAY", "extracted_unverified", "2026-01-01"),
    ]
    assert all(s["url"] == "owner-entered" for r in rows for s in r["sources"])
    assert c.post("/api/costs/providers", json=body).status_code == 400  # already there
    assert (
        c.post(
            "/api/costs/providers", json={**body, "name": "Other", "template_broker": "nobody"}
        ).status_code
        == 400
    )
    assert c.post("/api/costs/providers", json={**body, "valid_from": "x"}).status_code == 422
    assert audit_actions(conn) == ["costs.provider_added"]


def test_a_schedule_with_assumptions_shows_them_and_is_verified_only_with_them_accepted_and_audited(
    env,
):
    from algo.backtest.costs import schedule_store

    conn, app, clock = env
    doc = {**json.loads((CONFIG / "nse_cash_zerodha.json").read_text())["schedules"][0], "id": "early-with-assumptions",
           "valid_from": "2010-01-01", "valid_until": "2020-06-30", "assumptions": ["stamp duty was state-specific: 0.015% assumed"]}  # fmt: skip
    schedule_store.add(conn, doc, actor=None, now=clock.now())
    c = admin(conn, app, clock)
    row = next(
        r
        for r in c.get("/api/costs/schedules").json()["schedules"]
        if r["schedule_id"] == "early-with-assumptions"
    )
    assert row["assumptions"] == ["stamp duty was state-specific: 0.015% assumed"]
    url = f"/api/costs/schedules/early-with-assumptions/{VERSION}/verify"
    refused = c.post(url)
    assert refused.status_code == 400 and "accept the 1 assumption" in refused.json()["detail"]
    assert c.post(url, json={"accept_assumptions": False}).status_code == 400
    assert c.post(url, json={"accept_assumptions": True}).json() == {"ok": True}
    assert audit_actions(conn)[-1] == "costs.verified"
