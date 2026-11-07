from dataclasses import replace

from algo.strategy.lifecycle import RunSummary, promotion_blockers

CLEAN = RunSummary("strict", 0, 0, True, False, True, True, False, False)


def test_a_clean_strict_validated_run_is_eligible():
    assert promotion_blockers(CLEAN) == []


def test_research_mode_never_authorizes_promotion_even_if_everything_else_is_clean():
    (b,) = promotion_blockers(replace(CLEAN, reader_mode="research"))
    assert "strict" in b


def test_each_failure_is_reported_separately():
    bad = RunSummary("research", 3, 2, False, True, False, False, True, True)
    out = promotion_blockers(bad)
    assert len(out) == 9
    assert any("3 provisional" in x for x in out) and any("2 unpriced" in x for x in out)


def test_validation_protocol_is_required_on_top_of_a_clean_run():
    assert promotion_blockers(replace(CLEAN, validation_protocol_passed=False)) != []


R_STRICT = "run was not made in strict reader mode"
R_ACCOUNTING = "held positions passed through corporate actions the accounting cannot model"
R_LEDGER = "financial ledger does not reconcile"
R_UNVERIFIED = "cost schedules used are not verified (extracted or assumed rates)"
R_SLIPPAGE = "zero slippage: a strategy must survive realistic execution costs"
R_COSTS = "placeholder cost model: costs are not the versioned cost schedule"
R_VALIDATION = "validation protocol (walk-forward, deflated Sharpe, ...) has not passed"


def test_every_blocker_has_exactly_this_wording():
    from dataclasses import replace

    assert promotion_blockers(replace(CLEAN, reader_mode="research")) == [R_STRICT]
    assert promotion_blockers(replace(CLEAN, provisional_events=2)) == [
        "2 provisional (unverified) corporate-action estimates used"
    ]
    assert promotion_blockers(replace(CLEAN, unapplied_events=1)) == [
        "1 unpriced corporate actions affect the prices"
    ]
    assert promotion_blockers(replace(CLEAN, accounting_complete=False)) == [R_ACCOUNTING]
    assert promotion_blockers(replace(CLEAN, ledger_reconciled=False)) == [R_LEDGER]
    assert promotion_blockers(replace(CLEAN, placeholder_costs=True)) == [R_COSTS]
    assert promotion_blockers(replace(CLEAN, unverified_cost_schedules=True)) == [R_UNVERIFIED]
    assert promotion_blockers(replace(CLEAN, zero_slippage=True)) == [R_SLIPPAGE]
    assert promotion_blockers(replace(CLEAN, validation_protocol_passed=False)) == [R_VALIDATION]


def test_all_blockers_together_come_in_a_stable_order():
    out = promotion_blockers(RunSummary("research", 3, 2, False, True, False, False, True, True))
    assert out == [
        R_STRICT,
        "3 provisional (unverified) corporate-action estimates used",
        "2 unpriced corporate actions affect the prices",
        R_ACCOUNTING,
        R_LEDGER,
        R_COSTS,
        R_UNVERIFIED,
        R_SLIPPAGE,
        R_VALIDATION,
    ]
