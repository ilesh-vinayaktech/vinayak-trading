# ruff: noqa: E501, F811
"""A generated definition's buy/sell decisions for one stock on the chart: stored values inside the stored window, the days after it computed in memory, nothing written."""

import pytest

from algo.core.clock import SimClock
from algo.data.readiness import Readiness
from algo.factory import generate
from algo.factory import registry as freg
from algo.features import job, store
from tests.integration.alpha.test_run import world  # noqa: F401 - 8 stocks, stored ret_5d/ret_20d to the development end (2026-02-28), bars to early March
from tests.integration.features.test_store import NOW
from tests.support.portal import add_user, make_app, settings, sign_in

pytestmark = pytest.mark.integration
DEFN = generate.definition_for(
    generate.Hypothesis(1, 1, "ret_20d", "1", 1, "POSITIVE", 0.05, 0.001)
)  # daily
URL = f"/api/strategies/definitions/{DEFN.strategy_id}/1/signals"


@pytest.fixture
def chart(world, pg_url, tmp_path):
    conn, ids, fid = world
    store.set_status(conn, "traded_value_20d", "1", "USABLE", by="owner", reason="test", now=NOW)
    from tests.integration.alpha.test_run import JAN

    job.run(conn, fid, JAN, NOW, "abc", ready=lambda c, n: Readiness())
    freg.register(conn, DEFN, by="agent", reason="generated", now=NOW)
    clock = SimClock(NOW)
    add_user(conn, clock, "TRADER", "jane@example.com")
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    conn.commit()
    return conn, ids, make_app(pg_url, tmp_path, portal=settings(clock))


def test_only_people_who_may_use_strategies_read_a_definitions_decisions(chart):
    conn, ids, app = chart
    q = {"instrument_id": ids[0], "start": "2026-01-02", "end": "2026-02-27"}
    assert sign_in(app, "viewer@example.com").get(URL, params=q).status_code == 403


def test_the_decisions_run_through_the_stored_window_and_on_into_the_days_computed_after_it(chart):
    conn, ids, app = chart
    c = sign_in(app, "jane@example.com")
    r = c.get(URL, params={"instrument_id": ids[0], "start": "2026-01-02", "end": "2026-03-06"})
    assert r.status_code == 200, r.text
    body = r.json()
    days = [d["day"] for d in body["days"]]
    assert (
        days[0] >= "2026-01-02" and days[-1] > "2026-02-28"
    )  # decisions continue past the development end, computed on the spot
    assert any("kept nowhere" in n for n in body["notes"]) and body["strategy"].endswith("v1")
    after = [d for d in body["days"] if d["day"] > "2026-02-28"]
    assert after and all(d["ready"] for d in after)  # the computed days have values for the stock
    assert conn.execute(
        "SELECT count(*) FROM feature_run WHERE month >= '2026-03-01'"
    ).fetchone() == (0,)  # nothing was stored


def test_a_range_wholly_after_the_stored_window_is_computed_too_and_a_bad_request_is_refused(chart):
    conn, ids, app = chart
    c = sign_in(app, "jane@example.com")
    r = c.get(URL, params={"instrument_id": ids[0], "start": "2026-03-02", "end": "2026-03-06"})
    assert r.status_code == 200 and r.json()["days"]
    assert (
        c.get(
            URL, params={"instrument_id": ids[0], "start": "2026-03-06", "end": "2026-03-02"}
        ).status_code
        == 422
    )
    assert (
        c.get(
            URL, params={"instrument_id": ids[0], "start": "2010-01-01", "end": "2026-03-02"}
        ).status_code
        == 422
    )  # over 11 years
    assert (
        c.get(
            URL, params={"instrument_id": 999999, "start": "2026-01-02", "end": "2026-02-01"}
        ).status_code
        == 404
    )
    assert (
        c.get(
            "/api/strategies/definitions/ALPHA_NOPE_H1/1/signals",
            params={"instrument_id": ids[0], "start": "2026-01-02", "end": "2026-02-01"},
        ).status_code
        == 404
    )


def test_the_decisions_are_kept_and_a_later_request_computes_only_the_new_days(chart, monkeypatch):
    from algo.factory import signals as sig

    conn, ids, app = chart
    c = sign_in(app, "jane@example.com")
    asked: list[list] = []
    real = sig.compute
    monkeypatch.setattr(
        sig,
        "compute",
        lambda conn_, defn, iid, days, *a, **kw: (
            asked.append(list(days)),
            real(conn_, defn, iid, days, *a, **kw),
        )[1],
    )
    q = {"instrument_id": ids[0], "start": "2026-01-02"}
    first = c.get(URL, params={**q, "end": "2026-03-04"}).json()
    assert len(asked) == 1 and len(asked[0]) == len(first["days"])
    series = conn.execute("SELECT first_day, last_day FROM definition_signal_series").fetchall()
    assert len(series) == 1 and str(series[0][1]) == first["days"][-1]["day"]
    again = c.get(URL, params={**q, "end": "2026-03-04"}).json()
    assert len(asked) == 2 and asked[1] == []  # nothing new: served from the stored decisions
    assert again == first
    longer = c.get(URL, params={**q, "end": "2026-03-06"}).json()
    assert [d.isoformat() for d in asked[2]] == [
        "2026-03-05",
        "2026-03-06",
    ]  # only the two new sessions were computed
    assert [d["day"] for d in longer["days"]][: len(first["days"])] == [
        d["day"] for d in first["days"]
    ]
    assert [(d["action"], d["holding_after"]) for d in longer["days"][: len(first["days"])]] == [
        (d["action"], d["holding_after"]) for d in first["days"]
    ]
    assert conn.execute("SELECT count(*) FROM definition_signal_day").fetchone() == (
        len(longer["days"]),
    )


def test_a_request_that_starts_before_the_kept_range_recomputes_and_replaces_it(chart, monkeypatch):
    from algo.factory import signals as sig

    conn, ids, app = chart
    c = sign_in(app, "jane@example.com")
    asked: list[list] = []
    real = sig.compute
    monkeypatch.setattr(
        sig,
        "compute",
        lambda conn_, defn, iid, days, *a, **kw: (
            asked.append(list(days)),
            real(conn_, defn, iid, days, *a, **kw),
        )[1],
    )
    c.get(URL, params={"instrument_id": ids[0], "start": "2026-02-02", "end": "2026-03-04"})
    wider = c.get(
        URL, params={"instrument_id": ids[0], "start": "2026-01-12", "end": "2026-03-04"}
    ).json()
    assert len(asked) == 2 and len(asked[1]) == len(wider["days"])  # the whole wider range
    assert (
        conn.execute("SELECT first_day FROM definition_signal_series").fetchone()[0].isoformat()
        == wider["days"][0]["day"]
    )
    assert conn.execute("SELECT count(*) FROM definition_signal_series").fetchone() == (1,)
