"""The API's real responses, frozen as JSON the frontend parses with its own schemas
(frontend/tests/contract). If an endpoint changes shape, this test fails until the fixtures are
regenerated (UPDATE_CONTRACT=1) - and then the frontend schema test fails until the UI is adapted.
Both sides are therefore tested against what the API actually returns, not hand-written mocks."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from algo.core.clock import SimClock
from algo.data.benchmark import ingest, register, store_validation
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.integration.test_app import NOW, docs, write  # noqa: F401
from tests.support.portal import open_app

pytestmark = pytest.mark.integration
OUT = Path(__file__).parents[2] / "frontend" / "tests" / "contract"


@pytest.fixture
def seeded(conn, pg_url, docs):  # noqa: F811
    migrate(conn)
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
        " VALUES ('s','1','{}','ph','c','research','{}','{}','{}','[]','[]','[]','[]',true,0,'{\"sharpe\": 1.2}','rh',%s,true,'{}','{}')", (NOW,))  # fmt: skip
    clock = SimClock(datetime(2026, 11, 8, 4, 51, tzinfo=UTC))
    return TestClient(open_app(pg_url, docs, clock=clock)), iid, bid


def snapshots(c, iid, bid):
    rng = {"start": "2025-06-01", "end": "2025-06-30"}
    return {
        "health": c.get("/api/health"),
        "dashboard": c.get("/api/dashboard"),
        "instrument_search": c.get("/api/instruments", params={"q": "xy"}),
        "instrument_detail": c.get(f"/api/instruments/{iid}"),
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
