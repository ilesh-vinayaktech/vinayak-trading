# ruff: noqa: E501
"""Where an overfitting probability (PBO) comes from, for one study's variants.

Callers: scripts/pbo_diagnostic.py and tests/unit/research/test_pbo_diagnostic.py. Nothing similar exists: algo.backtest.validation.stats.pbo_cscv returns only the final number and the logits.
User's request: a PBO diagnostic report (per variant, the spread over partitions, how often each variant wins in sample and where it ranks out of sample, whether poor ranks cluster in
particular periods, whether a few partitions drive it). Read-only: it changes no gate and no threshold.

It repeats the gate's own method (combinatorially symmetric cross-validation over `n_blocks` blocks, the in-sample winner's out-of-sample rank) but keeps every partition so the number can be taken apart."""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import combinations
from statistics import mean
from typing import Any

from algo.backtest.validation.stats import pbo_cscv, sharpe_per_period

N_BLOCKS = 8
THRESHOLD = 0.2  # the gate's allowed PBO (config/validation_thresholds.json), for the 'how many partitions would have to change' line


def _score(returns: Sequence[float], rows: list[int]) -> float:
    s = sharpe_per_period([returns[i] for i in rows])
    return 0.0 if s is None else s


def partitions(series: Sequence[Sequence[float]], n_blocks: int) -> list[dict[str, Any]]:
    """Every choice of half the blocks as in-sample: the winner, its out-of-sample rank (1 = worst) and logit, and the scores."""
    n, t = len(series), len(series[0])
    size = t // n_blocks
    blocks = [range(b * size, (b + 1) * size) for b in range(n_blocks)]
    out = []
    for ins in combinations(range(n_blocks), n_blocks // 2):
        is_rows = [i for b in ins for i in blocks[b]]
        oos_blocks = [b for b in range(n_blocks) if b not in ins]
        oos_rows = [i for b in oos_blocks for i in blocks[b]]
        is_scores = [_score(series[k], is_rows) for k in range(n)]
        oos_scores = [_score(series[k], oos_rows) for k in range(n)]
        winner = is_scores.index(max(is_scores))
        rank = 1 + sum(s < oos_scores[winner] for s in oos_scores)
        omega = rank / (n + 1)
        out.append(
            {
                "in_blocks": list(ins), "out_blocks": oos_blocks, "winner": winner, "rank": rank, "logit": math.log(omega / (1 - omega)),
                "is_score": is_scores[winner], "oos_score": oos_scores[winner], "oos_mean": mean(oos_scores), "oos_scores": oos_scores,
            }
        )  # fmt: skip
    return out


def _quantiles(xs: list[float]) -> list[float]:
    s = sorted(xs)
    return [s[round(q * (len(s) - 1))] for q in (0.0, 0.25, 0.5, 0.75, 1.0)]


def diagnose(
    series: Sequence[Sequence[float]], configs: Sequence[str], block_names: Sequence[str]
) -> dict[str, Any]:
    """`series[k]` is variant k's daily returns (equal length); `configs[k]` its label; `block_names[b]` names block b of the history (for the regime table)."""
    n = len(series)
    if n < 2:
        raise ValueError("need at least 2 variants")
    parts = partitions(series, N_BLOCKS)
    bad = [p for p in parts if p["logit"] <= 0]
    pbo = len(bad) / len(parts)
    by_config = []
    for k in range(n):
        won = [p for p in parts if p["winner"] == k]
        by_config.append(
            {
                "config": configs[k], "winner_count": len(won), "winner_share": len(won) / len(parts),
                "mean_oos_rank_when_winner": mean(p["rank"] for p in won) if won else None,
                "pbo_when_winner": sum(p["logit"] <= 0 for p in won) / len(won) if won else None,
                "mean_oos_rank_overall": mean(1 + sum(s < p["oos_scores"][k] for s in p["oos_scores"]) for p in parts),
                "mean_is_sharpe_when_winner": mean(p["is_score"] for p in won) if won else None,
                "mean_oos_sharpe_when_winner": mean(p["oos_score"] for p in won) if won else None,
            }
        )  # fmt: skip
    by_config.sort(key=lambda x: -x["winner_count"])
    size = len(series[0]) // N_BLOCKS
    by_block = []
    for b in range(N_BLOCKS):
        in_oos = [p for p in parts if b in p["out_blocks"]]
        block_rows = range(b * size, (b + 1) * size)
        by_block.append(
            {
                "block": block_names[b] if b < len(block_names) else f"b{b}",
                "avg_variant_annual_return": mean(sum(series[k][i] for i in block_rows) / len(block_rows) * 252 for k in range(n)),
                "pbo_when_out_of_sample": sum(p["logit"] <= 0 for p in in_oos) / len(in_oos),
                "pbo_when_in_sample": sum(p["logit"] <= 0 for p in parts if b in p["in_blocks"]) / (len(parts) - len(in_oos)),
            }
        )  # fmt: skip
    need = max(0, math.ceil(len(bad) - THRESHOLD * len(parts) - 1e-9))
    sensitivity = {nb: pbo_cscv(series, nb).pbo for nb in (4, 6, 8, 10)}
    return {
        "pbo": pbo, "partitions": len(parts), "bad_partitions": len(bad), "flips_needed_for_threshold": need,
        "by_config": by_config, "by_block": by_block, "sensitivity_to_block_count": sensitivity,
        "distribution": {
            "logit_quantiles": _quantiles([p["logit"] for p in parts]),  # min, 25%, median, 75%, max (the gate counts logits at or below 0)
            "winner_is_rank_mean": mean(p["rank"] for p in parts), "winner_oos_rank_counts": {r: sum(p["rank"] == r for p in parts) for r in range(1, n + 1)},
            "winner_is_sharpe_mean": mean(p["is_score"] for p in parts), "winner_oos_sharpe_mean": mean(p["oos_score"] for p in parts), "all_oos_sharpe_mean": mean(p["oos_mean"] for p in parts),
        },
    }  # fmt: skip
