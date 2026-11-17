from algo.research.pipeline import next_step


def test_a_new_study_starts_with_its_trials_then_the_verdict():
    assert next_step({}, None) == ("trials", False)
    assert next_step({"trials": "DONE"}, None) == ("verdict", False)


def test_a_study_waits_while_a_run_is_queued_or_running():
    assert next_step({"trials": "RUNNING"}, None) == (None, False)
    assert next_step({"trials": "DONE", "verdict": "QUEUED"}, None) == (None, False)
    assert next_step({"trials": "DONE", "verdict": "DONE", "holdout": "RUNNING"}, True) == (
        None,
        False,
    )


def test_a_run_that_ended_without_a_result_ends_the_study():
    assert next_step({"trials": "FAILED"}, None) == (None, True)
    assert next_step({"trials": "DONE", "verdict": "CANCELLED"}, None) == (None, True)


def test_only_a_passed_verdict_goes_on_to_the_inner_holdout():
    assert next_step({"trials": "DONE", "verdict": "DONE"}, False) == (None, True)
    assert next_step({"trials": "DONE", "verdict": "DONE"}, True) == ("holdout", False)
    assert next_step({"trials": "DONE", "verdict": "DONE", "holdout": "DONE"}, True) == (None, True)
    assert next_step({"trials": "DONE", "verdict": "DONE", "holdout": "FAILED"}, True) == (
        None,
        True,
    )
