from algo.api import scorecards


def dq(**kw):
    return {"completeness": "PASS", "continuity": "PASS", **kw}


def build(**over):
    base = {
        "dq": dq(),
        "latest_run": {"accounting_complete": True, "ledger_reconciled": True},
        "quarantined": [],
        "validation": {"reports": 4, "passed": 1, "holdout_consumed": True},
        "jobs": [
            {"name": "a", "last_run": {"status": "ok"}},
            {"name": "b", "last_run": {"status": "ok"}},
        ],
        "heartbeat_problems": [],
        "kite_state": "connected",
    }
    return scorecards.build(**{**base, **over})


def item(card, name):
    return next(i for i in card["items"] if i["name"] == name)


def test_three_separate_scorecards_each_with_its_own_status_and_never_one_blended_number():
    s = build()
    assert set(s) == {"platform_correctness", "strategy_validity", "operational_reliability"}
    for card in s.values():
        assert card["status"] == "OK" and card["items"]


def test_platform_correctness_fails_on_a_failed_check_or_an_unreconciled_ledger_and_is_incomplete_when_evidence_is_missing():
    assert build(dq=dq(continuity="FAIL"))["platform_correctness"]["status"] == "FAIL"
    bad = {"accounting_complete": True, "ledger_reconciled": False}
    assert build(latest_run=bad)["platform_correctness"]["status"] == "FAIL"
    assert (
        build(latest_run={"accounting_complete": False, "ledger_reconciled": True})[
            "platform_correctness"
        ]["status"]
        == "FAIL"
    )
    assert build(quarantined=["2026-11-06"])["platform_correctness"]["status"] == "FAIL"
    never = build(dq=dq(continuity=None))["platform_correctness"]
    assert (
        never["status"] == "INCOMPLETE" and item(never, "price continuity")["status"] == "UNKNOWN"
    )
    assert (
        build(latest_run=None)["platform_correctness"]["status"] == "INCOMPLETE"
    )  # no backtest has produced a ledger yet
    assert build(dq=dq(completeness=None))["platform_correctness"]["status"] == "INCOMPLETE"


def test_strategy_validity_says_how_much_evidence_exists_and_never_calls_nothing_a_pass():
    unproven = build(validation={"reports": 4, "passed": 1, "holdout_consumed": False})[
        "strategy_validity"
    ]
    assert unproven["status"] == "INCOMPLETE" and item(unproven, "holdout")["status"] == "UNKNOWN"
    none = build(validation={"reports": 0, "passed": 0, "holdout_consumed": False})[
        "strategy_validity"
    ]
    assert (
        none["status"] == "INCOMPLETE" and item(none, "development evidence")["status"] == "UNKNOWN"
    )
    failing = build(validation={"reports": 5, "passed": 0, "holdout_consumed": False})[
        "strategy_validity"
    ]
    assert (
        failing["status"] == "ATTENTION"
        and "no development report has passed" in item(failing, "development evidence")["detail"]
    )
    assert (
        build(validation={"reports": 5, "passed": 2, "holdout_consumed": True})[
            "strategy_validity"
        ]["status"]
        == "OK"
    )


def test_operational_reliability_counts_failed_and_never_run_jobs_silent_processes_and_the_kite_session():
    jobs = [
        {"name": "a", "last_run": {"status": "failed"}},
        {"name": "b", "last_run": None},
        {"name": "c", "last_run": {"status": "ok"}},
    ]
    s = build(jobs=jobs)["operational_reliability"]
    assert s["status"] == "FAIL" and "1 job(s) failed" in item(s, "scheduled jobs")["detail"]
    assert (
        build(heartbeat_problems=["live feed: silent for 12 min"])["operational_reliability"][
            "status"
        ]
        == "FAIL"
    )
    assert build(kite_state="expired")["operational_reliability"]["status"] == "ATTENTION"
    assert build(kite_state=None)["operational_reliability"]["status"] == "ATTENTION"
    never = build(jobs=[{"name": "a", "last_run": None}])["operational_reliability"]
    assert (
        never["status"] == "INCOMPLETE"
    )  # nothing has run, so nothing has failed: that is not reliability
    some_never = build(
        jobs=[{"name": "a", "last_run": {"status": "ok"}}, {"name": "b", "last_run": None}]
    )["operational_reliability"]
    assert (
        some_never["status"] == "OK"
        and "1 never ran" in item(some_never, "scheduled jobs")["detail"]
    )
