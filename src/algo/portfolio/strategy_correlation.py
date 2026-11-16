# ruff: noqa: E501
"""How alike the strategies' daily returns are: strategies that move together add little when combined (plan.md phase 5, correlation report).

Callers: scripts/strategy_correlation.py and tests/unit/portfolio/test_strategy_correlation.py. Reuses algo.portfolio.allocation.correlation. Read-only: it recommends nothing and moves no money.
User's instruction (standing): "keep taking things one by one from @TODO.md and @plan.md ... keep things finishing with test"."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from algo.portfolio.allocation import correlation


def matrix(returns: Mapping[str, Sequence[float]]) -> dict[str, dict[str, float | None]]:
    """Pearson correlation for every pair, over the last days every series has; None where a series does not vary."""
    n = min(len(r) for r in returns.values())
    cut = {k: list(v)[-n:] for k, v in returns.items()}
    return {a: {b: correlation(cut[a], cut[b]) for b in cut} for a in cut}


def near_copies(
    m: Mapping[str, Mapping[str, float | None]], threshold: float
) -> list[tuple[str, str, float]]:
    """Each pair (once) whose correlation is at or above `threshold`."""
    names = sorted(m)
    return [
        (a, b, c)
        for i, a in enumerate(names)
        for b in names[i + 1 :]
        if (c := m[a][b]) is not None and c >= threshold
    ]


def report(returns: Mapping[str, Sequence[float]], threshold: float = 0.8) -> str:
    m = matrix(returns)
    names = sorted(m)
    width = max(len(n) for n in names)
    lines = ["".ljust(width) + "  " + "  ".join(n[:8].rjust(8) for n in names)]
    for a in names:
        lines.append(
            a.ljust(width)
            + "  "
            + "  ".join(("   n/a   " if m[a][b] is None else f"{m[a][b]:8.2f}") for b in names)
        )
    pairs = near_copies(m, threshold)
    lines.append("")
    lines.append(
        "no pair is above the threshold: combining them diversifies"
        if not pairs
        else f"These move together (correlation at or above {threshold}), so combining them adds little: "
        + "; ".join(f"{a} and {b} ({c:.2f})" for a, b, c in pairs)
    )
    return "\n".join(lines)
