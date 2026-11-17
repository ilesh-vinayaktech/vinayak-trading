"""The API's real responses, frozen as JSON the frontend parses with its own schemas
(frontend/tests/contract). If an endpoint changes shape, this test fails until the fixtures are
regenerated (UPDATE_CONTRACT=1) - and then the frontend schema test fails until the UI is adapted.
Both sides are therefore tested against what the API actually returns, not hand-written mocks."""

import json
import os
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from algo.core.clock import SimClock
from algo.data.benchmark import ingest, register, store_validation
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.integration.test_app import NOW, docs, write  # noqa: F401
from tests.support.portal import open_app
from tests.support.research_lock import anchor_open_lock

pytestmark = pytest.mark.integration
OUT = Path(__file__).parents[2] / "frontend" / "tests" / "contract"


@pytest.fixture
def seeded(conn, pg_url, docs):  # noqa: F811
    migrate(conn)
    anchor_open_lock(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "XYZ")
    for i, d in enumerate([(2025, 6, 9), (2025, 6, 10), (2025, 6, 11), (2025, 6, 12)]):
        ts = datetime(*d, 3, 45, tzinfo=UTC)
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,"
            "ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'nse',1,%s)",
            (iid, ts, 100 + i, 102 + i, 99 + i, 101 + i, 1000 * (i + 1), NOW))  # fmt: skip
    for ex, kind, status in (("2025-06-11", "bonus", "ok"), ("2025-06-12", "demerger", "review")):
        conn.execute(
            "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,num,den,subject,knowledge_time,"
            "knowledge_time_source,source,raw_checksum,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,'t',%s,"
            "'ex_date_proxy','nse','x',%s)", (iid, ex, kind, status, 2 if kind == "bonus" else None,
                                             1 if kind == "bonus" else None, NOW, NOW))  # fmt: skip
    for i in range(6):  # six Kite minutes from 09:15 IST on 2025-06-09
        conn.execute(
            "INSERT INTO bar_1m (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,"
            "dataset_version,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'kite','2025-06-30',1,%s)",
            (iid, datetime(2025, 6, 9, 3, 45 + i, tzinfo=UTC), 100 + i, 101 + i, 99 + i, 100 + i, 10 * (i + 1), NOW))  # fmt: skip
    bid = register(
        conn,
        name="N200",
        provider="p",
        index_symbol="NIFTY 200",
        return_type="TOTAL_RETURN",
        methodology_version="m",
    )
    from datetime import date
    from decimal import Decimal as D

    ingest(
        conn,
        bid,
        [(date(2024, 1, d), D(100 + d)) for d in (1, 2, 3)],
        source="s",
        source_timestamp=NOW,
        raw_hash="h",
        now=NOW,
    )
    store_validation(conn, bid, report={"report_version": "2", "technical_validation_passed": True, "check_states": {"a": "PASS"},
                                        "owner_accepted_findings": [{"check": "a", "state": "UNRESOLVED", "label": "L", "reason": "r", "detail_sha256": "h"}]},
                     passed=True, normalized_sha256="n", factsheet_sha256=None, unresolved=["x"], now=NOW)  # fmt: skip
    for part, status in (
        ("2025-06-09", "quarantined"),
        ("2025-06-09", "loaded"),
        ("2025-06-10", "loaded"),
    ):
        conn.execute(
            "INSERT INTO partition_load (source,dataset,partition,status,at) VALUES ('nse','bhav',%s,%s,%s)",
            (part, status, NOW),
        )
    conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,"
        "cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,"
        "accounting_complete,dividends_received,metrics,result_hash,created_at,ledger_reconciled,reconciliation,pnl)"
        " VALUES ('s','1','{}','ph','c','research','{\"initial_cash\": \"10000\", \"start\": \"2025-06-09\", \"end\": \"2025-06-12\"}','{}','{}','[]','[]','[]','[]',true,0,'{\"sharpe\": 1.2}','rh',%s,true,'{}','{}')", (NOW,))  # fmt: skip
    conn.execute(
        "INSERT INTO backtest_trade (run_id,seq,day,instrument_id,side,qty,price,cost) VALUES "
        "(1,1,'2025-06-09',%s,'BUY',10,100,2),(1,2,'2025-06-12',%s,'SELL',10,104,2),(1,3,'2025-06-12',%s,'BUY',5,104,1)",
        (iid, iid, iid),
    )
    conn.execute("INSERT INTO backtest_equity VALUES (1,'2025-06-09',10000),(1,'2025-06-12',10035)")
    fid = conn.execute(
        "INSERT INTO fundamental_filing (symbol,isin,instrument_id,seq_number,period_start,period_end,basis,audited,"
        "bank,filed_at,rounding,xbrl_url,raw_sha256,ingested_at) VALUES ('XYZ','INE000X01010',%s,'IF1','2025-04-01',"
        "'2025-06-30','CONSOLIDATED',true,false,%s,'Crores','u','h',%s) RETURNING filing_id",
        (iid, datetime(2025, 7, 10, 13, tzinfo=UTC), NOW),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO fundamental_fact VALUES (%s,'Income','QUARTER',745250000000),(%s,'ProfitLossForPeriod','QUARTER',139340000000),"
        "(%s,'BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations','QUARTER',38.37),"
        "(%s,'Assets','INSTANT',1907820000000),(%s,'CashFlowsFromUsedInOperatingActivities','YTD',258010000000),"
        "(%s,'Equity','INSTANT',1199940000000),(%s,'PaidUpValueOfEquityShareCapital','QUARTER',3620000000),"
        "(%s,'FaceValueOfEquityShareCapital','QUARTER',1)",
        (fid,) * 8,
    )
    clock = SimClock(datetime(2026, 11, 8, 4, 51, tzinfo=UTC))
    return TestClient(open_app(pg_url, docs, clock=clock)), iid, bid


def snapshots(c, iid, bid):
    rng = {"start": "2025-06-01", "end": "2025-06-30"}
    return {
        "health": c.get("/api/health"),
        "dashboard": c.get("/api/dashboard"),
        "instrument_search": c.get("/api/instruments", params={"q": "xy"}),
        "instrument_detail": c.get(f"/api/instruments/{iid}"),
        "instrument_fundamentals": c.get(f"/api/instruments/{iid}/fundamentals"),
        "instrument_ratios": c.get(f"/api/instruments/{iid}/ratios"),
        "bars_none": c.get(f"/api/instruments/{iid}/bars", params={**rng, "adjust": "none"}),
        "bars_split": c.get(f"/api/instruments/{iid}/bars", params={**rng, "adjust": "split"}),
        "bars_5m": c.get(f"/api/instruments/{iid}/bars", params={**rng, "timeframe": "5m"}),
        "indicator_catalog": c.get("/api/indicators"),
        "indicator_series": c.get(
            f"/api/instruments/{iid}/indicators",
            params={**rng, "names": "sma:2,macd:2:3:2,supertrend:2:1"},
        ),
        "benchmark_list": c.get("/api/benchmarks"),
        "benchmark_detail": c.get(f"/api/benchmarks/{bid}"),
        "benchmark_levels": c.get(f"/api/benchmarks/{bid}/levels"),
        "backtests": c.get("/api/backtests"),
        "backtest_report": c.get("/api/backtests/1/report"),
        "activity": c.get("/api/system/activity"),
    }


def test_the_api_responses_match_the_fixtures_the_frontend_is_tested_against(seeded):
    c, iid, bid = seeded
    for name, resp in snapshots(c, iid, bid).items():
        assert resp.status_code == 200, name
        text = json.dumps(resp.json(), indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        if os.environ.get("UPDATE_CONTRACT") == "1":
            path.write_text(text)
        assert path.read_text() == text, f"{name}: the API response changed; run UPDATE_CONTRACT=1"


def test_the_review_worklist_matches_the_fixture_the_frontend_is_tested_against(seeded, conn):
    c, iid, _ = seeded
    conn.execute(
        "INSERT INTO instrument_alias (instrument_id, source, source_symbol, valid_from)"
        " VALUES (%s,'nse','XYZ','2000-01-01')",
        (iid,),
    )
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,reason,subject,"
        "knowledge_time,knowledge_time_source,source,raw_checksum,ingested_at) VALUES"
        " (%s,'2025-06-10','demerger','review','no ratio or price in the feed','Demerger',%s,"
        "'ex_date_proxy','nse','x',%s)",
        (iid, NOW, NOW),
    )
    resp = c.get("/api/corporate-actions/review")
    assert resp.status_code == 200
    text = json.dumps(resp.json(), indent=1, sort_keys=True) + "\n"
    path = OUT / "corporate_action_review.json"
    if os.environ.get("UPDATE_CONTRACT") == "1":
        path.write_text(text)
    assert path.read_text() == text, "the API response changed; run UPDATE_CONTRACT=1"


def test_the_sign_in_responses_match_the_fixtures_the_frontend_is_tested_against(
    conn, pg_url, tmp_path
):
    """The portal's own shapes (login, me, sessions, 2FA). Random values (ids, seeds, codes, times) are replaced by
    placeholders so the frozen JSON is stable; only the SHAPE is under test."""
    from fastapi.testclient import TestClient

    from algo.portal import accounts, totp
    from tests.support.portal import FAST, make_app

    migrate(conn)
    now = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
    accounts.create_user(
        conn,
        FAST,
        email="jane@example.com",
        display_name="Jane Roe",
        role="TRADER",
        password="violet-harbor-lantern-42",
        now=now,
    )
    c = TestClient(make_app(pg_url, tmp_path))
    login = c.post(
        "/api/auth/login",
        json={"email": "jane@example.com", "password": "violet-harbor-lantern-42"},
    )
    c.headers["x-csrf-token"] = c.cookies.get("csrf", "")
    enrol = c.post("/api/auth/mfa/enrol")
    code = totp.code_at(enrol.json()["secret"], int(now.timestamp()) // 30)
    confirm = c.post("/api/auth/mfa/confirm", json={"code": code})
    mfa_step = TestClient(make_app(pg_url, tmp_path)).post(
        "/api/auth/login",
        json={"email": "jane@example.com", "password": "violet-harbor-lantern-42"},
    )
    shots = {
        "auth_login": login, "auth_me": c.get("/api/auth/me"), "auth_sessions": c.get("/api/auth/sessions"),
        "auth_mfa_enrol": enrol, "auth_mfa_confirm": confirm, "auth_mfa_required": mfa_step,
    }  # fmt: skip

    def scrub(v, key=""):
        if isinstance(v, dict):
            return {k: scrub(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [scrub(x, key) for x in v]
        if key in ("id", "session_id", "secret", "uri", "created_at", "last_seen_at", "expires_at"):
            return f"<{key}>"
        if key == "recovery_codes" or (isinstance(v, str) and len(v) == 11 and v[5] == "-"):
            return "<recovery code>"
        return v

    for name, resp in shots.items():
        assert resp.status_code == 200, (name, resp.text)
        text = json.dumps(scrub(resp.json()), indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        if os.environ.get("UPDATE_CONTRACT") == "1":
            path.write_text(text)
        assert path.read_text() == text, f"{name}: the API response changed; run UPDATE_CONTRACT=1"


def test_the_user_administration_responses_match_the_fixtures_the_frontend_is_tested_against(
    conn, pg_url, tmp_path
):
    """Directory, profile, invitation, reset link and audit shapes (random ids, times and tokens scrubbed)."""
    import re

    from algo.core.clock import SimClock
    from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

    migrate(conn)
    clock = SimClock(datetime(2026, 11, 11, 10, 0, tzinfo=UTC))
    app = make_app(pg_url, tmp_path, portal=settings(clock))
    add_user(conn, clock, "ADMIN", "boss@example.com", name="The Boss")
    jane = add_user(conn, clock, "TRADER", "jane@example.com", name="Jane Roe")
    c = sign_in(app, "boss@example.com")
    enrol_second_factor(c, clock)
    invite = c.post(
        "/api/users", json={"email": "new@example.com", "name": "New Hire", "role": "VIEWER"}
    )
    shots = {
        "users_list": c.get("/api/users"),
        "user_detail": c.get(f"/api/users/{jane}"),
        "user_invite": invite,
        "user_invite_link": c.post(f"/api/users/{invite.json()['id']}/resend-invite"),
        "user_reset_link": c.post(f"/api/users/{jane}/reset-password"),
        "audit": c.get("/api/audit", params={"limit": 3}),
    }

    def scrub(v, key=""):
        if isinstance(v, dict):
            return {k: scrub(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [scrub(x, key) for x in v]
        if key == "id" and isinstance(v, int):
            return 0  # an audit entry's sequence number
        if key in ("id", "actor_user_id", "target_id") and isinstance(v, str):
            return f"<{key}>"
        if key in ("id", "at", "created_at", "last_login_at", "password_changed_at"):
            return f"<{key}>" if v is not None else None
        if isinstance(v, str):
            return re.sub(r"token=[\w-]+", "token=<token>", v)
        return v

    for name, resp in shots.items():
        assert resp.status_code == 200, (name, resp.text)
        text = json.dumps(scrub(resp.json()), indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        if os.environ.get("UPDATE_CONTRACT") == "1":
            path.write_text(text)
        assert path.read_text() == text, f"{name}: the API response changed; run UPDATE_CONTRACT=1"


def test_the_kite_connection_responses_match_the_fixtures_the_frontend_is_tested_against(
    conn, pg_url, tmp_path
):
    """The user's own Kite connection shapes. They must never carry the key, secret or token, so the fixtures also prove that."""
    import json as _json

    from algo.core.clock import SimClock
    from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

    migrate(conn)
    clock = SimClock(datetime(2026, 11, 11, 10, 0, tzinfo=UTC))
    st = settings(clock)
    object.__setattr__(st, "public_url", "https://portal.example")
    object.__setattr__(
        st,
        "kite_http",
        lambda m, u, h, d=None: (
            200,
            _json.dumps(
                {"status": "success", "data": {"access_token": "TOKEN-XYZ", "user_id": "AB1234"}}
            ).encode(),
        ),
    )
    app = make_app(pg_url, tmp_path, portal=st)
    add_user(conn, clock, "ADMIN", "boss@example.com", name="The Boss")
    c = sign_in(app, "boss@example.com")
    enrol_second_factor(c, clock)
    shots = {"kite_connection_empty": c.get("/api/kite/connection")}
    c.post(
        "/api/kite/credentials",
        json={"api_key": "abcd1234efgh5678", "api_secret": "zyxw9876vuts5432"},
    )
    login = c.post("/api/kite/connect/start")
    shots["kite_login"] = login
    state = login.json()["login_url"].split("state%3D")[1]
    shots["kite_complete"] = c.post(
        "/api/kite/connect/complete", json={"request_token": "REQ", "state": state}
    )
    c.post("/api/kite/system", json={"enabled": True})
    shots["kite_connection"] = c.get("/api/kite/connection")
    shots["kite_system"] = c.get("/api/kite/system")

    def scrub(v, key=""):
        if isinstance(v, dict):
            return {k: scrub(x, k) for k, x in v.items()}
        if key in ("connected_at", "token_expires_at") and isinstance(v, str):
            return f"<{key}>"
        if key == "owner_id":
            return "<owner_id>"
        if key == "login_url":
            return v.split("redirect_params=")[0] + "redirect_params=state%3D<state>"
        return v

    for name, resp in shots.items():
        assert resp.status_code == 200, (name, resp.text)
        assert "TOKEN-XYZ" not in resp.text and "zyxw9876vuts5432" not in resp.text
        text = json.dumps(scrub(resp.json()), indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        if os.environ.get("UPDATE_CONTRACT") == "1":
            path.write_text(text)
        assert path.read_text() == text, f"{name}: the API response changed; run UPDATE_CONTRACT=1"


def test_the_crm_and_ticket_responses_match_the_fixtures_the_frontend_is_tested_against(
    conn, pg_url, tmp_path
):
    """Notes, tags, tasks, staff and tickets (random ids and times scrubbed): the UI schemas parse exactly these."""
    import re

    from algo.core.clock import SimClock
    from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

    migrate(conn)
    clock = SimClock(datetime(2026, 11, 11, 10, 0, tzinfo=UTC))
    app = make_app(pg_url, tmp_path, portal=settings(clock))
    jane = add_user(conn, clock, "TRADER", "jane@example.com", name="Jane Roe")
    ops_id = add_user(conn, clock, "OPERATOR", "ops@example.com", name="Olive Ops")
    staff = sign_in(app, "ops@example.com")
    enrol_second_factor(staff, clock)
    janes = sign_in(app, "jane@example.com")
    staff.post(f"/api/users/{jane}/notes", json={"body": "Asked about Kite"})
    staff.post(f"/api/users/{jane}/tags", json={"tag": "kyc pending"})
    created = staff.post(
        "/api/tasks",
        json={
            "title": "Call Jane",
            "owner_id": str(ops_id),
            "user_id": str(jane),
            "due_date": "2026-11-15",
        },
    )
    number = janes.post(
        "/api/tickets",
        json={"subject": "Cannot connect Kite", "body": "Invalid token", "priority": "HIGH"},
    ).json()["number"]
    ticket_id = janes.get("/api/tickets").json()["items"][0]["id"]
    staff.post(
        f"/api/tickets/{ticket_id}/messages", json={"body": "Check expiry", "internal": True}
    )
    staff.post(f"/api/tickets/{ticket_id}/messages", json={"body": "Which browser?"})
    shots = {
        "notes": staff.get(f"/api/users/{jane}/notes"), "tags": staff.get("/api/tags"), "staff": staff.get("/api/staff"),
        "tasks": staff.get("/api/tasks"), "task_created": created, "tickets": staff.get("/api/tickets"),
        "ticket_created": janes.post("/api/tickets", json={"subject": "Second", "body": "b"}),
        "ticket_requester_view": janes.get(f"/api/tickets/{ticket_id}"), "ticket_staff_view": staff.get(f"/api/tickets/{ticket_id}"),
    }  # fmt: skip
    assert number >= 1

    def scrub(v, key=""):
        if isinstance(v, dict):
            return {k: scrub(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [scrub(x, key) for x in v]
        if key == "number" and isinstance(v, int):
            return 0
        if key in ("id", "owner_id", "about_id", "requester_id", "assignee_id") and isinstance(
            v, str
        ):
            return f"<{key}>"
        if key in ("created_at", "updated_at", "completed_at") and isinstance(v, str):
            return f"<{key}>"
        return re.sub(r"token=[\w-]+", "token=<token>", v) if isinstance(v, str) else v

    for name, resp in shots.items():
        assert resp.status_code == 200, (name, resp.text)
        text = json.dumps(scrub(resp.json()), indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        if os.environ.get("UPDATE_CONTRACT") == "1":
            path.write_text(text)
        assert path.read_text() == text, f"{name}: the API response changed; run UPDATE_CONTRACT=1"
    assert (
        "Check expiry" not in shots["ticket_requester_view"].text
        and "Check expiry" in shots["ticket_staff_view"].text
    )


def test_the_dashboard_responses_match_the_fixtures_the_frontend_is_tested_against(
    conn, pg_url, tmp_path
):
    """Both dashboards, with ids and times scrubbed. Neither may carry a key, secret or token."""
    from algo.core.clock import SimClock
    from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

    migrate(conn)
    clock = SimClock(datetime(2026, 11, 11, 10, 0, tzinfo=UTC))
    app = make_app(pg_url, tmp_path, portal=settings(clock))
    boss_id = add_user(conn, clock, "ADMIN", "boss@example.com", name="The Boss")
    add_user(conn, clock, "TRADER", "jane@example.com", name="Jane Roe")
    c = sign_in(app, "boss@example.com")
    enrol_second_factor(c, clock)
    jane = sign_in(app, "jane@example.com")
    jane.post("/api/tickets", json={"subject": "Help with Kite", "body": "x"})
    c.post("/api/tasks", json={"title": "Call", "owner_id": str(boss_id), "due_date": "2026-11-01"})
    shots = {
        "dashboard_me": jane.get("/api/dashboard/me"),
        "dashboard_operations": c.get("/api/dashboard/operations"),
    }

    def scrub(v, key=""):
        if isinstance(v, dict):
            return {k: scrub(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [scrub(x, key) for x in v]
        if key in ("at", "updated_at", "last_login_at", "ticket_id") and isinstance(v, str):
            return f"<{key}>"
        if key == "id" and isinstance(v, int):
            return 0
        return v

    for name, resp in shots.items():
        assert resp.status_code == 200, (name, resp.text)
        text = json.dumps(scrub(resp.json()), indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        if os.environ.get("UPDATE_CONTRACT") == "1":
            path.write_text(text)
        assert path.read_text() == text, f"{name}: the API response changed; run UPDATE_CONTRACT=1"


def test_the_market_calendar_response_matches_the_fixture_the_frontend_is_tested_against(
    conn, pg_url, tmp_path
):
    from algo.core.clock import SimClock
    from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

    migrate(conn)
    clock = SimClock(datetime(2026, 11, 12, 10, 0, tzinfo=UTC))
    app = make_app(pg_url, tmp_path, portal=settings(clock))
    add_user(conn, clock, "OPERATOR", "ops@example.com", name="Olive Ops")
    c = sign_in(app, "ops@example.com")
    enrol_second_factor(c, clock)
    c.post(
        "/api/market/sessions",
        json={
            "day": "2026-11-14",
            "start": "09:15",
            "end": "10:00",
            "note": "Special live session",
        },
    )
    conn.execute(
        "INSERT INTO market_session (session_date, kind, note, source, created_at) VALUES"
        " ('2026-11-24','CLOSED','Prakash Gurpurb Sri Guru Nanak Dev','nse',%s),"
        " ('2026-11-28','CLOSED','Special Muhurat*','nse',%s)",
        (clock.now(), clock.now()),
    )
    resp = c.get("/api/market/calendar")
    assert resp.status_code == 200
    doc = resp.json()
    for row in doc["exceptions"]:
        row["id"] = 0
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    path = OUT / "market_calendar.json"
    if os.environ.get("UPDATE_CONTRACT") == "1":
        path.write_text(text)
    assert path.read_text() == text, (
        "market_calendar: the API response changed; run UPDATE_CONTRACT=1"
    )


def test_the_paper_trading_responses_match_the_fixtures_the_frontend_is_tested_against(
    conn, pg_url, tmp_path, monkeypatch
):
    monkeypatch.delenv(
        "ALGO_LIVE", raising=False
    )  # the gate answer must not depend on the machine running the test
    from decimal import Decimal as D

    from psycopg.types.json import Jsonb

    from algo.core.clock import SimClock
    from algo.data.store.instruments import InstrumentRepo
    from algo.paper import book
    from tests.support.bt import put_bars
    from tests.support.portal import add_user, make_app, settings, sign_in

    migrate(conn)
    anchor_open_lock(conn)
    start = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
    today = start.date()
    clock = SimClock(start)
    app = make_app(pg_url, tmp_path, portal=settings(clock))
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    a, b = repo.add_instrument(x, "RELIANCE"), repo.add_instrument(x, "TCS")
    put_bars(conn, a, {today - timedelta(days=1): D("2850"), today: D("2900")})
    uid = add_user(conn, clock, "TRADER", "jane@example.com")
    c = sign_in(app, "jane@example.com")
    shots = {"paper_account_none": c.get("/api/paper/account")}
    c.post(
        "/api/paper/account",
        json={
            "initial_cash": "1000000",
            "universe": "nifty200",
            "max_instruments": 100,
            "timeframe": "1D",
            "params": {},
        },
    )
    shots["paper_account"] = c.get("/api/paper/account")
    made = c.post(
        "/api/strategies",
        json={
            "name": "Cautious",
            "universe": "nifty100",
            "max_instruments": 50,
            "timeframe": "1D",
            "params": {"entry_rsi": 30},
        },
    ).json()["config_id"]
    c.post(f"/api/strategies/{made}/use", json={})
    c.post(
        f"/api/strategies/{made}/stage", json={"to_stage": "PAPER", "reason": "prove the plumbing"}
    )
    shots["strategies"] = c.get("/api/strategies")
    shots["strategy_stage"] = c.get(f"/api/strategies/{made}/stage")
    from tests.integration.portal.test_strategy_routes import _series

    infy = repo.add_instrument(x, "INFY")
    sig_days = _series(conn, infy)
    shots["strategy_signals"] = c.get(
        f"/api/strategies/{made}/signals",
        params={
            "instrument_id": infy,
            "start": sig_days[250].isoformat(),
            "end": sig_days[-1].isoformat(),
        },
    )
    from algo.live.bar_store import save_quotes, save_status
    from algo.live.ticks import Tick

    save_status(conn, "CONNECTED", "497 instruments", subscribed=497, last_tick_at=start, last_bar_at=None, ticks=1, bars=0, bad_frames=0, late_ticks=0, now=start)  # fmt: skip
    save_quotes(conn, {738561: Tick(738561, D("2900"), 1000, start, D("2850"), D("2905"), D("2845"), D("2850"))}, {738561: a}, start)  # fmt: skip
    shots["live"] = c.get(f"/api/live/{a}")
    from pathlib import Path

    from algo.backtest.costs import schedule_store
    from algo.data import freeze as data_freeze
    from tests.unit.research.test_study import spec as study_spec

    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,dataset_version,ingested_at)"
        " VALUES (%s,%s,1,1,1,1,1,'kite',%s,1,%s)",
        (
            a,
            datetime.combine(today - timedelta(days=1), time(3, 45), UTC),
            today - timedelta(days=1),
            start,
        ),
    )
    data_freeze.take(conn, "kite", today - timedelta(days=1), start, "contract")
    schedule_store.import_files(
        conn, Path(__file__).resolve().parents[1] / "fixtures/cost_schedules", now=start
    )
    shots["study_options"] = c.get("/api/studies/options")
    made_study = c.post(
        "/api/studies",
        json=study_spec(end=(today - timedelta(days=1)).isoformat()).model_dump(mode="json"),
    ).json()["experiment_id"]
    shots["studies"] = c.get("/api/studies")
    shots["study"] = c.get(f"/api/studies/{made_study}")
    from algo.research import study_jobs

    run_id = c.post(f"/api/studies/{made_study}/runs").json()["run_id"]
    study_jobs.start(
        conn,
        run_id,
        12,
        1,
        {
            "universe_coverage": [
                {
                    "list": "2023-12-31",
                    "from": "2024-02-01",
                    "until": "2024-07-31",
                    "in_segments": 250,
                    "matched": 244,
                    "usable": 238,
                }
            ]
        },
        start,
    )
    study_jobs.save_trial(
        conn,
        made_study,
        {"entry_rsi": 20, "trend_sma": 200},
        "h",
        "DONE",
        start,
        metrics={
            "sharpe": 1.25,
            "cagr": 0.12,
            "max_drawdown": -0.09,
            "trades": 100,
            "costs": 5000.5,
        },
        returns=[0.01],
        seconds=12.5,
    )
    shots["study_results"] = c.get(f"/api/studies/{made_study}/results")
    shots["study_verdict_none"] = c.get(f"/api/studies/{made_study}/verdict")
    from algo.backtest.validation.gates import Evidence, Thresholds, evaluate
    from algo.backtest.validation.registry import save_report
    from algo.research.study import default_thresholds

    run_id = conn.execute(
        "INSERT INTO backtest_run (strategy_id,strategy_version,params,params_hash,code_version,reader_mode,config,"
        "cost_model,adjustment_versions,provisional_events,unapplied_events,blocked_instruments,unmodelled_events,"
        "accounting_complete,dividends_received,metrics,result_hash,created_at,ledger_reconciled,reconciliation,pnl)"
        " VALUES ('s','1','{}','ph','c','research','{}','{}','{}','[]','[]','[]','[]',true,0,'{}','rh',%s,true,'{}','{}')"
        " RETURNING run_id", (start,)).fetchone()[0]  # fmt: skip
    th = Thresholds(**{k: float(v) for k, v in default_thresholds().items()})
    ev = Evidence(oos_sharpe=1.1, dsr=0.97, pbo=0.1, max_drawdown=-0.2, benchmark_max_drawdown=-0.3, benchmark_sharpe=0.7,
                  plateau_drop=0.1, sharpe_2x_costs=0.6, top3_instrument=0.4, top3_month=0.3, top3_trade=0.2,
                  oos_days=252.0, regimes=2.0, window_share=0.4)  # fmt: skip
    save_report(conn, made_study, run_id, evaluate(ev, th, "confirmed"), ev, 12, start, refs={
        "chosen": {"entry_rsi": 20, "trend_sma": 200}, "benchmark": "Nifty 200 Total Return Index (gross)", "benchmark_note": None,
        "windows": [{"train_from": "2020-01-01", "train_to": "2021-12-31", "test_from": "2022-01-07", "test_to": "2022-07-01",
                     "chosen": {"entry_rsi": 20}, "sharpe": 1.4, "return": 0.08}],
        "walk_forward": {"train": 504, "test": 126, "embargo": 5}, "cost_2x_run": run_id, "capital_run": run_id, "capital_multiple": "3",
    })  # fmt: skip
    shots["study_verdict_before_holdout"] = c.get(f"/api/studies/{made_study}/verdict")
    conn.execute(
        "INSERT INTO study_holdout (experiment_id, run_id, passed, evidence, gates, refs, created_at) VALUES (%s,%s,false,%s,%s,%s,%s)",
        (made_study, run_id,
         '{"days": 60, "sharpe": 0.4, "max_drawdown": -0.1, "benchmark_sharpe": null, "total_return": 0.03}',
         '[{"name": "holdout_sharpe", "passed": false, "detail": "0.40 < required 0.8"}, {"name": "holdout_drawdown", "passed": true, "detail": "ok"}, {"name": "holdout_beats_benchmark", "passed": false, "detail": "evidence missing"}]',
         '{"chosen": {"entry_rsi": 20}, "benchmark": "Nifty 200 Total Return Index (gross)", "benchmark_note": "not loaded", "window": ["2024-05-01", "2026-11-06"], "verdict_report": 1}',
         start),
    )  # fmt: skip
    shots["study_verdict"] = c.get(f"/api/studies/{made_study}/verdict")
    book.record_fill(
        conn,
        uid,
        day=today,
        side="BUY",
        iid=a,
        qty=D(100),
        price=D("2850.5"),
        commission=D("28.5"),
        charges=[("STT", D("285"))],
        ref="seed",
        now=start,
    )
    conn.execute(
        "INSERT INTO paper_equity (user_id, day, equity, cash) VALUES (%s,%s,1000000,1000000),(%s,%s,1004600,714686.5)",
        (uid, today - timedelta(days=1), uid, today),
    )
    for _sym, iid, status, side in (
        ("RELIANCE", a, "FILLED", "BUY"),
        ("TCS", b, "PENDING", "BUY"),
        ("TCS", b, "FAILED", "SELL"),
    ):
        conn.execute(
            "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, status, created_at, not_before, expires_at, fill_price, fill_commission, fill_day, failure)"
            " VALUES (%s,%s,%s,%s,10,3500,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (uid, today, iid, side, "entry: oversold in an uptrend", status, start, start, start + timedelta(hours=20),
             D("2850.5") if status == "FILLED" else None, D("28.5") if status == "FILLED" else None, today if status == "FILLED" else None,
             "you do not hold that many shares" if status == "FAILED" else None),
        )  # fmt: skip
    conn.execute(
        "INSERT INTO paper_run (user_id, decision_day, strategy_id, strategy_version, params_hash, status, detail, created_at) VALUES (%s,%s,'trend_pullback','1','h','PROPOSED',%s,%s)",
        (uid, today, Jsonb({"label": "UNVALIDATED", "universe": {"universe": "nifty200"}}), start),
    )
    shots["paper_summary"] = c.get("/api/paper/summary")
    shots["paper_orders"] = c.get("/api/paper/orders")
    shots["paper_runs"] = c.get("/api/paper/runs")
    shots["paper_live_status"] = c.get("/api/paper/live-status")
    for k, (fg, label, trend) in enumerate(
        [(41.0, "Fear", "SIDEWAYS"), (52.5, "Neutral", "SIDEWAYS"), (63.5, "Greed", "BULL")]
    ):
        conn.execute(
            "INSERT INTO market_regime_daily (day, universe, advancers, decliners, unchanged, n50, above50, n200, above200, highs, lows, fear_greed, label, trend, volatility, components, computed_at)"
            " VALUES (%s,1600,900,600,100,1500,600,1400,800,45,12,%s,%s,%s,'NORMAL',%s,%s)",
            (
                datetime(2026, 11, 9 + k, tzinfo=UTC).date(),
                fg,
                label,
                trend,
                '{"momentum": 80.5, "breadth": 20.0, "volatility": 55.0, "stocks_vs_bonds": null}',
                datetime(2026, 11, 12, 4, tzinfo=UTC),
            ),
        )
    shots["market_zone"] = c.get("/api/market/zone")
    for symbol, drift in (("NIFTY 500", 0.0005), ("NIFTY BANK", 0.0015), ("NIFTY IT", -0.0005)):
        level = 1000.0
        for i in range(300):
            level *= 1 + drift
            conn.execute(
                "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at) VALUES ('NSE',%s,%s,1,1,1,%s,1,%s)",
                (
                    symbol,
                    datetime(2026, 11, 12, tzinfo=UTC).date() - timedelta(days=299 - i),
                    round(level, 4),
                    datetime(2026, 11, 12, 4, tzinfo=UTC),
                ),
            )
    shots["market_sectors"] = c.get("/api/market/sectors")
    forecast_day = datetime(2026, 11, 11, tzinfo=UTC).date()
    for subject, h, p, live, up, r, ev in (
        (
            "MARKET",
            1,
            0.58,
            True,
            None,
            None,
            '[{"feature": "momentum", "value": 70.0, "effect": 0.21}]',
        ),
        ("MARKET", 5, 0.61, True, None, None, "[]"),
        ("IT", 1, 0.44, True, None, None, "[]"),
        ("IT", 5, 0.47, True, None, None, "[]"),
        ("MARKET", 1, 0.9, False, False, -0.02, "[]"),
        ("MARKET", 1, 0.55, False, True, 0.004, "[]"),
    ):
        conn.execute(
            "INSERT INTO prediction_log (as_of, subject, horizon_days, model_version, live, p_up, evidence, outcome_up, realized) VALUES (%s,%s,%s,'logit-v1',%s,%s,%s,%s,%s)",
            (
                forecast_day if live else forecast_day - timedelta(days=30 + int(p * 10)),
                subject,
                h,
                live,
                p,
                ev,
                up,
                r,
            ),
        )
    shots["market_forecast"] = c.get("/api/market/forecast")
    for k, (title, sent, syms) in enumerate(
        [
            ("Sensex surges as FII inflows return", 0.6, ["TCS"]),
            ("Nifty slides on recession fears", -0.5, ["TCS", "ITC"]),
            ("Board meeting on Thursday", None, []),
        ]
    ):
        conn.execute(
            "INSERT INTO news_item (item_id, source, title, url, published_at, first_seen_at, sentiment, hits, symbols) VALUES (%s,'economictimes',%s,%s,timestamptz '2026-11-11 08:00+00' - make_interval(hours => %s),timestamptz '2026-11-11 08:30+00',%s,1,%s)",
            (f"n{k}", title, f"https://example.com/{k}", k, sent, syms),
        )
    shots["market_news"] = c.get("/api/market/news")
    shots["screener_meta"] = c.get("/api/screener/meta")
    shots["screener_run_empty"] = c.post(
        "/api/screener/run",
        json={"preset": "top-swing-scores", "conditions": [], "match": "all", "limit": 5},
    )
    stock = conn.execute(
        "SELECT instrument_id, symbol FROM instrument WHERE asset_class='equity' AND instrument_id NOT IN (SELECT instrument_id FROM bar_1d) ORDER BY instrument_id LIMIT 1"
    ).fetchone()
    shots["market_score_unscored"] = c.get("/api/market/score", params={"symbol": stock[1]})
    for k in range(
        90
    ):  # a stock bouncing between about 100 and 110, ending just under its resistance
        level = round(105 + 5 * __import__("math").sin(2 * __import__("math").pi * k / 20), 2)
        conn.execute(
            "INSERT INTO bar_1d (instrument_id, ts, open, high, low, close, volume, series, delivery_qty, source, dataset_version, ingested_at)"
            " VALUES (%s, %s::date + time '03:45', %s, %s, %s, %s, %s, 'EQ', %s, 'nse', 1, now())",
            (
                stock[0],
                datetime(2026, 11, 11, tzinfo=UTC).date() - timedelta(days=89 - k),
                level,
                level + 0.3,
                level - 0.3,
                level,
                1000 + k,
                500,
            ),
        )
    shots["market_levels"] = c.get("/api/market/levels", params={"symbol": stock[1]})
    shots["risk_state"] = c.get("/api/risk")
    c.put("/api/risk/limits", json={"limits": {"max_order_value": "50000", "max_open_orders": 5}})
    c.post("/api/risk/switch", json={"action": "pause", "reason": "looking at the data"})
    shots["risk_state_paused"] = c.get("/api/risk")

    def scrub(v, key=""):
        if isinstance(v, dict):
            return {k: scrub(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [scrub(x, key) for x in v]
        return (
            f"<{key}>"
            if key in ("order_id", "config_id", "id", "owner_user_id", "requested_by", "sha256")
            else v
        )

    for name, resp in shots.items():
        assert resp.status_code == 200, (name, resp.text)
        doc = scrub(resp.json())
        if (
            name == "paper_orders"
        ):  # same-second orders come back in an arbitrary order: compare them in a fixed one
            doc["orders"].sort(key=lambda o: (o["status"], o["symbol"], o["side"]))
        text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        if os.environ.get("UPDATE_CONTRACT") == "1":
            path.write_text(text)
        assert path.read_text() == text, f"{name}: the API response changed; run UPDATE_CONTRACT=1"


def test_the_cost_responses_match_the_fixtures_the_frontend_is_tested_against(
    conn, pg_url, tmp_path
):
    from pathlib import Path

    from algo.backtest.costs.schedule_store import import_files
    from algo.core.clock import SimClock
    from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

    migrate(conn)
    start = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
    import_files(conn, Path(__file__).resolve().parents[1] / "fixtures/cost_schedules", now=start)
    clock = SimClock(start)
    app = make_app(pg_url, tmp_path, portal=settings(clock))
    add_user(conn, clock, "ADMIN", "boss@example.com", name="The Boss")
    c = sign_in(app, "boss@example.com")
    enrol_second_factor(c, clock)
    shots = {
        "costs_schedules": c.get("/api/costs/schedules"),
        "costs_preview": c.get(
            "/api/costs/preview?broker=zerodha&product=DELIVERY&side=BUY&qty=100&price=2850.5&day=2026-11-12"
        ),
    }
    for name, resp in shots.items():
        assert resp.status_code == 200, (name, resp.text)
        text = json.dumps(resp.json(), indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        if os.environ.get("UPDATE_CONTRACT") == "1":
            path.write_text(text)
        assert path.read_text() == text, f"{name}: the API response changed; run UPDATE_CONTRACT=1"


def test_the_research_intelligence_responses_match_the_fixtures_the_frontend_is_tested_against(
    conn, pg_url, tmp_path
):
    import random

    from fastapi.testclient import TestClient

    from algo.alpha import registry as alpha_registry
    from algo.alpha.discover import Evidence
    from algo.features import store as feature_store
    from algo.learning import memory
    from algo.portfolio import audit
    from tests.support.portal import open_app

    migrate(conn)
    now = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    feature_store.register_all(conn, now)
    alpha_registry.record(
        conn,
        [
            Evidence("ret_5d", "1", 5, 500, 150.0, 0.05, 0.1, 0.5, 0.6, 4.0, 0.0001),
            Evidence("ret_20d", "1", 20, 500, 150.0, 0.0, 0.1, 0.0, 0.5, 0.0, 0.9),
        ],
        "d" * 64,
        now,
    )
    from psycopg.types.json import Jsonb

    fids = dict(conn.execute("SELECT name, feature_id FROM feature_definition").fetchall())

    def report(passed, reasons, share, violations):
        return {"passed": passed, "reasons": reasons, "min_coverage": "0.90", "coverage": {"share": share, "eligible": 100, "valued": 99},
                "recompute": {"identical": True, "months": 3, "stored_months_checked": 2, "stored_match": True}, "lookahead": {"cuts": [], "checks": 40, "violations": violations}}  # fmt: skip

    conn.execute(
        "INSERT INTO feature_status (feature_id, status, reason, set_by, at) VALUES (%s,'USABLE','validated','agent',%s)",
        (fids["ret_5d"], now),
    )
    for name, rep in (
        ("ret_5d", report(True, [], "0.989657", 0)),
        (
            "vol_20d",
            report(
                False, ["look-ahead: 3 value(s) changed when later data was removed"], "0.95", 3
            ),
        ),
    ):
        conn.execute(
            "INSERT INTO feature_validation (feature_id, dataset_sha256, passed, report, created_by, created_at) VALUES (%s,%s,%s,%s,'agent',%s)",
            (fids[name], "a" * 64, rep["passed"], Jsonb(rep), now),
        )
    memory.add(
        conn,
        "DECISION",
        "capital",
        "Paper capital Rs 1 lakh",
        by="owner",
        now=now,
        tags=["decision"],
    )
    memory.sync_alpha(conn, now=now)
    rng = {k: random.Random(i) for i, k in enumerate("ABCD", 1)}
    returns = {
        k: [r.gauss(0.0005, 0.01 * (i + 1)) for _ in range(60)]
        for i, (k, r) in enumerate(rng.items())
    }
    audit.recommend_and_record(
        conn, returns, dict.fromkeys(returns, "OK"), by="jane", now=now, method="EQUAL_RISK"
    )
    conn.execute(
        "INSERT INTO dq_result (run_at, check_name, scope, subject, status, detail) VALUES (%s,'degradation','paper account vs backtest run 1',NULL,'FAIL','DEGRADED: mean return -0.5%% a day')",
        (now,),
    )
    import os as _os

    t = datetime.now(UTC)
    conn.execute(
        "INSERT INTO job_progress (job, label, pid, status, done, total, phase, message, started_at, updated_at, finished_at) VALUES ('feature_validation','Feature validation',%s,'RUNNING',3,12,'checking ret_20d','look-ahead test 2 of 5 (cut at 2024-03-01)',%s,%s,NULL)",
        (_os.getpid(), t, t),
    )
    conn.execute(
        "INSERT INTO job_progress (job, label, pid, status, done, total, phase, message, started_at, updated_at, finished_at) VALUES ('alpha_discovery','Alpha discovery',1,'DONE',4,4,'finished','4 hypotheses recorded',%s,%s,%s)",
        (t, t, t),
    )
    conn.commit()
    c = TestClient(open_app(pg_url, tmp_path))
    shots = {
        "intel_progress": c.get("/api/intel/progress"),
        "intel_funnel": c.get("/api/intel/funnel"),
        "intel_features": c.get("/api/intel/features"),
        "intel_overview": c.get("/api/intel/overview"),
        "intel_alpha": c.get("/api/intel/alpha"),
        "intel_notes": c.get("/api/intel/notes"),
        "intel_definitions": c.get("/api/intel/definitions"),
        "intel_allocations": c.get("/api/intel/allocations"),
    }
    for name, resp in shots.items():
        assert resp.status_code == 200, (name, resp.text)
        doc = json.loads(json.dumps(resp.json()))

        def scrub(v, key=""):
            if isinstance(v, dict):
                return {k: scrub(x, k) for k, x in v.items()}
            if isinstance(v, list):
                return [scrub(x, key) for x in v]
            if key in ("at", "started_at", "updated_at") and isinstance(v, str):
                return "<at>"
            if key in ("id", "elapsed_s", "quiet_s") and isinstance(v, int):
                return 0
            return v

        text = json.dumps(scrub(doc), indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        if os.environ.get("UPDATE_CONTRACT") == "1":
            path.write_text(text)
        assert path.read_text() == text, f"{name}: the API response changed; run UPDATE_CONTRACT=1"


def test_the_regulatory_response_matches_the_fixture_the_frontend_is_tested_against(
    conn, pg_url, tmp_path
):
    from datetime import date

    from algo.execution.regulatory import Item, record
    from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

    migrate(conn)
    clock = SimClock(datetime(2026, 11, 17, 10, 0, tzinfo=UTC))
    app = make_app(pg_url, tmp_path, portal=settings(clock))
    add_user(conn, clock, "OPERATOR", "ops@example.com", name="Olive Ops")
    c = sign_in(app, "ops@example.com")
    enrol_second_factor(c, clock)
    stale = Item(
        "NSE",
        "CM",
        "tagging",
        "Tag every algo order",
        date(2025, 4, 1),
        "circular B",
        date(2026, 9, 1),
        "owner",
    )
    record(conn, stale)  # last checked over 30 days ago
    c.post(
        "/api/regulatory",
        json={
            "topic": "ops_limit",
            "value": {"orders_per_second": 10},
            "source": "circular A",
            "effective_from": "2025-10-01",
        },
    )
    resp = c.get("/api/regulatory")
    assert resp.status_code == 200
    text = json.dumps(resp.json(), indent=1, sort_keys=True) + "\n"
    path = OUT / "regulatory.json"
    if os.environ.get("UPDATE_CONTRACT") == "1":
        path.write_text(text)
    assert path.read_text() == text, "regulatory: the API response changed; run UPDATE_CONTRACT=1"
