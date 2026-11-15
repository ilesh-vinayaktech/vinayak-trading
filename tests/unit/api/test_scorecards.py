from algo.api import scorecards


def dq(**kw):
    return {
        "completeness": "PASS",
        "continuity": "PASS",
        "freshness": "PASS",
        "kite_reconcile": "PASS",
        **kw,
    }


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
    assert build(dq=dq(freshness="FAIL"))["platform_correctness"]["status"] == "FAIL"
    assert build(dq=dq(kite_reconcile="FAIL"))["platform_correctness"]["status"] == "FAIL"
    assert build(dq=dq(kite_reconcile=None))["platform_correctness"]["status"] == "INCOMPLETE"


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


# ---- the exact words and states for two whole scenarios (reviewed by hand against the spec) ----
BAD_INPUT = {
    "dq": {
        "completeness": "PASS",
        "continuity": "FAIL",
        "freshness": None,
        "kite_reconcile": "PASS",
    },
    "latest_run": {"accounting_complete": True, "ledger_reconciled": False},
    "quarantined": ["2026-11-06", "2026-11-07"],
    "validation": {"reports": 5, "passed": 0, "holdout_consumed": False},
    "jobs": [
        {"name": "a", "last_run": {"status": "failed"}},
        {"name": "b", "last_run": None},
        {"name": "c", "last_run": {"status": "ok"}},
    ],
    "heartbeat_problems": ["feed: silent 12 min", "oms: never reported"],
    "kite_state": "expired",
}
GOOD_INPUT = {
    "dq": {
        "completeness": "PASS",
        "continuity": "PASS",
        "freshness": "PASS",
        "kite_reconcile": "PASS",
    },
    "latest_run": {"accounting_complete": True, "ledger_reconciled": True},
    "quarantined": [],
    "validation": {"reports": 4, "passed": 1, "holdout_consumed": True},
    "jobs": [{"name": "a", "last_run": {"status": "ok"}}, {"name": "b", "last_run": None}],
    "heartbeat_problems": [],
    "kite_state": "connected",
}
BAD_EXPECTED = {
    "platform_correctness": {
        "status": "FAIL",
        "items": [
            {
                "name": "bar completeness",
                "status": "PASS",
                "detail": "the newest completeness run found nothing",
            },
            {
                "name": "price continuity",
                "status": "FAIL",
                "detail": "the newest continuity run found a problem",
            },
            {
                "name": "data freshness",
                "status": "UNKNOWN",
                "detail": "the freshness check has never run",
            },
            {
                "name": "Kite against bhavcopy",
                "status": "PASS",
                "detail": "the newest reconciliation run found nothing",
            },
            {
                "name": "quarantined loads",
                "status": "FAIL",
                "detail": "2 partition(s) refused: 2026-11-06, 2026-11-07",
            },
            {
                "name": "ledger reconciliation",
                "status": "FAIL",
                "detail": "the newest backtest's ledger does not reconcile or its accounting is incomplete",
            },
        ],
    },
    "strategy_validity": {
        "status": "ATTENTION",
        "items": [
            {
                "name": "development evidence",
                "status": "WARN",
                "detail": "5 report(s) exist but no development report has passed: nothing is promotable",
            },
            {
                "name": "holdout",
                "status": "UNKNOWN",
                "detail": "the holdout has not been evaluated: no result is proven out of sample",
            },
        ],
    },
    "operational_reliability": {
        "status": "FAIL",
        "items": [
            {
                "name": "scheduled jobs",
                "status": "FAIL",
                "detail": "1 job(s) failed on their last run: a",
            },
            {
                "name": "running processes",
                "status": "FAIL",
                "detail": "feed: silent 12 min; oms: never reported",
            },
            {"name": "Kite session", "status": "WARN", "detail": "the Kite session is expired"},
        ],
    },
}
GOOD_EXPECTED = {
    "platform_correctness": {
        "status": "OK",
        "items": [
            {
                "name": "bar completeness",
                "status": "PASS",
                "detail": "the newest completeness run found nothing",
            },
            {
                "name": "price continuity",
                "status": "PASS",
                "detail": "the newest continuity run found nothing",
            },
            {
                "name": "data freshness",
                "status": "PASS",
                "detail": "the newest freshness run found nothing",
            },
            {
                "name": "Kite against bhavcopy",
                "status": "PASS",
                "detail": "the newest reconciliation run found nothing",
            },
            {"name": "quarantined loads", "status": "PASS", "detail": "none"},
            {
                "name": "ledger reconciliation",
                "status": "PASS",
                "detail": "the newest backtest's ledger reconciles",
            },
        ],
    },
    "strategy_validity": {
        "status": "OK",
        "items": [
            {
                "name": "development evidence",
                "status": "PASS",
                "detail": "1 of 4 development report(s) passed",
            },
            {
                "name": "holdout",
                "status": "PASS",
                "detail": "the one holdout evaluation has been run",
            },
        ],
    },
    "operational_reliability": {
        "status": "OK",
        "items": [
            {
                "name": "scheduled jobs",
                "status": "PASS",
                "detail": "all 1 job(s) that have run ended well; 1 never ran",
            },
            {
                "name": "running processes",
                "status": "PASS",
                "detail": "no expected process is silent",
            },
            {"name": "Kite session", "status": "PASS", "detail": "connected"},
        ],
    },
}


def test_a_failing_platform_is_reported_item_by_item_in_exact_words():
    assert scorecards.build(**BAD_INPUT) == BAD_EXPECTED


def test_a_healthy_platform_is_reported_item_by_item_in_exact_words():
    assert scorecards.build(**GOOD_INPUT) == GOOD_EXPECTED


def details(card):
    return [(i["name"], i["status"], i["detail"]) for i in card["items"]]


def test_nothing_recorded_yet_is_reported_as_no_evidence_in_exact_words():
    s = build(
        dq=dq(completeness=None, continuity=None, freshness=None, kite_reconcile=None),
        latest_run=None,
        validation={"reports": 0, "passed": 0, "holdout_consumed": False},
        jobs=[{"name": "a", "last_run": None}, {"name": "b", "last_run": None}],
        kite_state=None,
    )
    assert details(s["platform_correctness"]) == [
        ("bar completeness", "UNKNOWN", "the completeness check has never run"),
        ("price continuity", "UNKNOWN", "the continuity check has never run"),
        ("data freshness", "UNKNOWN", "the freshness check has never run"),
        ("Kite against bhavcopy", "UNKNOWN", "the reconciliation check has never run"),
        ("quarantined loads", "PASS", "none"),
        ("ledger reconciliation", "UNKNOWN", "no backtest has produced a ledger yet"),
    ]
    assert details(s["strategy_validity"]) == [
        ("development evidence", "UNKNOWN", "no validation report exists yet"),
        (
            "holdout",
            "UNKNOWN",
            "the holdout has not been evaluated: no result is proven out of sample",
        ),
    ]
    assert details(s["operational_reliability"]) == [
        ("scheduled jobs", "UNKNOWN", "none of the 2 jobs has run yet"),
        ("running processes", "PASS", "no expected process is silent"),
        ("Kite session", "WARN", "the Kite session is not connected"),
    ]


def test_several_failed_jobs_are_listed_in_order_five_at_most_and_a_clean_run_has_no_never_ran_note():
    failing = [{"name": n, "last_run": {"status": "failed"}} for n in "abcdefg"]
    d = details(build(jobs=failing)["operational_reliability"])[0]
    assert d == ("scheduled jobs", "FAIL", "7 job(s) failed on their last run: a, b, c, d, e")
    clean = details(build()["operational_reliability"])[0]
    assert clean == (
        "scheduled jobs",
        "PASS",
        "all 2 job(s) that have run ended well",
    )  # nothing "never ran": no suffix
    assert details(build(kite_state="expired")["operational_reliability"])[2] == (
        "Kite session",
        "WARN",
        "the Kite session is expired",
    )
