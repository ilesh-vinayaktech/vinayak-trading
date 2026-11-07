import pytest

from algo.backtest.validation.walkforward import Window, walk_forward, windows


def test_rolling_windows_step_by_test_length_with_an_embargo_gap():
    w = windows(30, train=10, test=5, embargo=2)
    assert w[0] == Window((0, 10), (12, 17))
    assert w[1] == Window((5, 15), (17, 22))
    assert w[-1].test[1] <= 30 and len(w) == 3  # a 4th would end at 32


def test_anchored_windows_always_start_at_zero_and_train_grows():
    w = windows(30, 10, 5, 0, anchored=True)
    assert all(x.train[0] == 0 for x in w) and w[1].train == (0, 15)
    for x in w:  # train strictly before test, never overlapping
        assert x.train[1] <= x.test[0]


def test_no_window_when_history_is_too_short_and_bad_arguments_refused():
    assert windows(9, 5, 5) == []
    for args in ((10, 0, 5, 0), (10, 5, 0, 0), (10, 5, 5, -1)):
        with pytest.raises(ValueError, match="positive"):
            windows(*args)


def make_run(table):
    """Returns for a param are table[param] repeated; the series index is irrelevant here."""

    def run(p, start, end):
        base = table[p["k"]]
        return [base + 0.001 * ((i % 3) - 1) for i in range(start, end)]

    return run


def test_the_best_training_parameter_is_chosen_and_judged_out_of_sample():
    grid = [{"k": "bad"}, {"k": "good"}]
    r = walk_forward(40, grid, make_run({"bad": -0.001, "good": 0.002}), train=10, test=5)
    assert all(c == {"k": "good"} for c in r.chosen)
    assert len(r.oos_returns) == 5 * len(r.chosen) and len(r.per_window_sharpe) == len(r.chosen)
    assert all(s > 0 for s in r.per_window_sharpe)


def test_training_data_never_reaches_the_test_window():
    seen = []

    def run(p, start, end):
        seen.append((start, end))
        return [0.001 * (i % 2) for i in range(start, end)]

    walk_forward(30, [{"a": 1}], run, train=10, test=5, embargo=3)
    train_calls, test_calls = seen[0::2], seen[1::2]  # one param: train then test per window
    for (_, tr_end), (te_start, _) in zip(train_calls, test_calls, strict=True):
        assert te_start - tr_end == 3


def test_undefined_training_sharpe_loses_and_ties_go_to_the_first_entry():
    def run(p, start, end):
        if p["k"] == "flat":
            return [0.0] * (end - start)  # zero variance => undefined Sharpe
        return [0.001 * (i % 2) for i in range(start, end)]

    r = walk_forward(20, [{"k": "flat"}, {"k": "ok"}, {"k": "ok2"}], run, train=8, test=4)
    assert r.chosen[0] == {"k": "ok"}  # ok and ok2 tie; the earlier wins


def test_walk_forward_refuses_an_empty_grid_or_short_history():
    with pytest.raises(ValueError, match="^empty parameter grid$"):
        walk_forward(40, [], lambda *a: [], train=10, test=5)
    with pytest.raises(ValueError, match="^history too short for even one window$"):
        walk_forward(5, [{"a": 1}], lambda *a: [], train=10, test=5)
