"""Walk-forward evaluation: choose parameters on a training window, judge them on the NEXT window,
which the choice never saw. An embargo gap between the two stops overlapping holding periods and
lagged features leaking train information into the test window."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from algo.backtest.validation.stats import sharpe_per_period

Params = Mapping[str, Any]


@dataclass(frozen=True)
class Window:
    train: tuple[int, int]  # half-open [start, end) indices into the session list
    test: tuple[int, int]


def windows(
    n: int, train: int, test: int, embargo: int = 0, *, anchored: bool = False
) -> list[Window]:
    """Rolling (or anchored-at-0) windows over `n` sessions, stepping by `test`."""
    if min(train, test) < 1 or embargo < 0:
        raise ValueError("train and test must be positive and embargo non-negative")
    out: list[Window] = []
    start = 0
    while True:
        tr_end = start + train
        te_start = tr_end + embargo
        if te_start + test > n:
            return out
        out.append(Window((0 if anchored else start, tr_end), (te_start, te_start + test)))
        start += test


@dataclass(frozen=True)
class WalkForward:
    chosen: tuple[Params, ...]  # parameters picked in each window
    oos_returns: tuple[float, ...]  # test-window returns, concatenated in time order
    per_window_sharpe: tuple[float | None, ...]


Run = Callable[[Params, int, int], Sequence[float]]  # (params, start, end) -> period returns


def walk_forward(
    n: int,
    grid: Sequence[Params],
    run: Run,
    *,
    train: int,
    test: int,
    embargo: int = 0,
    anchored: bool = False,
) -> WalkForward:
    if not grid:
        raise ValueError("empty parameter grid")
    wins = windows(n, train, test, embargo, anchored=anchored)
    if not wins:
        raise ValueError("history too short for even one window")
    chosen: list[Params] = []
    oos: list[float] = []
    per: list[float | None] = []
    for w in wins:
        scored = [(sharpe_per_period(run(p, *w.train)), i) for i, p in enumerate(grid)]
        # undefined Sharpe ranks last; ties go to the earlier grid entry (deterministic)
        best = max(scored, key=lambda t: (t[0] is not None, t[0] or 0.0, -t[1]))[1]
        r = list(run(grid[best], *w.test))
        chosen.append(grid[best])
        oos.extend(r)
        per.append(sharpe_per_period(r))
    return WalkForward(tuple(chosen), tuple(oos), tuple(per))
