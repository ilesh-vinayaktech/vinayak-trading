from decimal import Decimal as D

import pytest

from algo.learning import ai_gateway as ai

M = "2026-11"


def ok_provider(tokens=100, rupees=D("0.5")):
    return lambda p: ai.Reply("42", tokens, rupees)


def run(provider, payload=None, ledger=None, **kw):
    kw.setdefault("estimate_tokens", 100)
    kw.setdefault("estimate_rupees", D(1))
    return ai.ask(
        provider, payload or {"q": "hi"}, ledger=ledger or ai.Ledger(), month=M, validate=int, **kw
    )


def test_a_good_call_returns_the_validated_value_and_books_real_usage():
    led = ai.Ledger()
    out = run(ok_provider(120, D("0.7")), ledger=led)
    assert (
        out == ai.Outcome(True, 42, "")
        and led.used(M) == (120, D("0.7"))
        and led.used("2026-12") == (0, D(0))
    )


def test_no_provider_means_no_ai_and_no_error():
    assert run(None) == ai.Outcome(False, reason="no provider configured")


def test_token_and_rupee_budgets_are_enforced_before_the_call_at_the_edge():
    called = []
    prov = lambda p: called.append(1) or ai.Reply("1", 1, D(0))  # noqa: E731
    led = ai.Ledger()
    led.book(M, 249_900, D(0))
    assert run(prov, ledger=led).ok  # 249,900 + 100 = exactly the limit
    out = run(prov, ledger=led, estimate_tokens=100)
    assert not out.ok and "token budget" in out.reason and len(called) == 1
    led2 = ai.Ledger()
    led2.book(M, 0, D(999))
    assert run(prov, ledger=led2, estimate_rupees=D(1)).ok
    led3 = ai.Ledger()
    led3.book(M, 0, D(999))
    out = run(prov, ledger=led3, estimate_rupees=D("1.01"))
    assert not out.ok and "rupee budget" in out.reason and len(called) == 2


def test_last_months_spend_does_not_count():
    led = ai.Ledger()
    led.book("2026-10", 250_000, D(1000))
    assert run(ok_provider(), ledger=led).ok


def test_market_and_holdout_data_never_leave():
    for bad in ({"bars": 1}, {"x": {"Holdout": 1}}, {"x": [{"prices": 1}]}, {"x": list(range(21))}):
        out = run(ok_provider(), bad)
        assert not out.ok and out.reason.startswith("payload refused")
    assert run(ok_provider(), {"x": list(range(20)), "flags": [True] * 30, "names": ["a"] * 30}).ok


def test_provider_failure_is_contained_and_costs_nothing():
    def boom(p):
        raise TimeoutError("slow")

    led = ai.Ledger()
    out = run(boom, ledger=led)
    assert out == ai.Outcome(False, reason="provider failed: TimeoutError") and led.rows == []


def test_bad_output_is_rejected_but_still_paid_for():
    led = ai.Ledger()
    out = ai.ask(
        lambda p: ai.Reply("not a number", 50, D(1)), {"q": 1}, ledger=led, month=M,
        estimate_tokens=50, estimate_rupees=D(1), validate=int,
    )  # fmt: skip
    assert (
        not out.ok
        and out.reason.startswith("output rejected: ValueError")
        and led.used(M) == (50, D(1))
    )


def test_default_budget_is_the_decided_one():
    assert ai.Budget() == ai.Budget(250_000, D(1000))
    with pytest.raises(AttributeError):
        ai.Budget().tokens = 1  # type: ignore[misc]


def test_refusals_name_the_path_and_say_false_and_the_provider_gets_the_payload():
    assert (
        run(ok_provider(), {"a": {"bars": 1}}).reason
        == "payload refused: payload.a.bars: this kind of data never goes to a model"
    )
    assert run(ok_provider(), {"a": [1, {"holdout": 1}]}).reason.startswith(
        "payload refused: payload.a[1].holdout:"
    )
    assert (
        run(ok_provider(), {"x": list(range(25))}).reason
        == "payload refused: payload.x: a series of 25 numbers looks like market data (limit 20)"
    )
    seen = []
    run(lambda p: seen.append(p) or ai.Reply("1", 1, D(0)), {"q": "hi"})
    assert seen == [{"q": "hi"}]
    led = ai.Ledger()
    led.book(M, 250_000, D(0))
    bad_rows = [
        run(ok_provider(), {"bars": 1}),
        run(ok_provider(), ledger=led),
        run(lambda p: ai.Reply("x", 1, D(0))),
        run(None),
    ]
    assert [o.ok for o in bad_rows] == [False] * 4
    assert all(o.ok is False for o in bad_rows)
    boom = run(lambda p: 1 / 0)
    assert boom.ok is False
    over = run(ok_provider(), estimate_rupees=D(1001))
    assert over.ok is False
