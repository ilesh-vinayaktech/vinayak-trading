# ruff: noqa: E501
"""The PBO diagnostic: where the overfitting probability comes from (which variants win in sample, how they rank out of sample, which blocks and how few partitions drive it)."""

import random

import pytest

from algo.backtest.validation.stats import pbo_cscv
from algo.research import pbo_diagnostic as pd


def noise(seed, n=160, drift=0.0):
    r = random.Random(seed)
    return [drift + r.gauss(0, 0.01) for _ in range(n)]


def test_the_partition_table_reproduces_the_gates_own_pbo_exactly():
    series = [noise(i) for i in range(5)]
    d = pd.diagnose(series, [f"c{i}" for i in range(5)], [f"b{i}" for i in range(8)])
    assert d["pbo"] == pytest.approx(pbo_cscv(series, 8).pbo) and d["partitions"] == 70
    assert (
        sum(x["winner_count"] for x in d["by_config"]) == 70
    )  # every partition has exactly one in-sample winner


def test_a_variant_with_a_real_edge_wins_nearly_every_partition_and_hardly_ever_overfits():
    best = noise(1, drift=0.004)  # a real, strong effect
    series = [best, *[noise(i + 10) for i in range(4)]]
    d = pd.diagnose(series, list("abcde"), [f"b{i}" for i in range(8)])
    top = d["by_config"][0]
    assert (
        top["config"] == "a"
        and top["winner_count"] >= 60
        and top["pbo_when_winner"] == 0.0
        and d["pbo"] <= 0.15
    )
    assert (
        d["flips_needed_for_threshold"] == 0 and d["by_block"][0]["pbo_when_out_of_sample"] <= 0.3
    )


def test_pure_noise_overfits_about_half_the_time_and_the_diagnostic_says_how_few_partitions_would_change_the_verdict():
    series = [noise(i + 40) for i in range(9)]
    d = pd.diagnose(series, [str(i) for i in range(9)], [f"b{i}" for i in range(8)])
    assert 0.25 < d["pbo"] < 0.75
    assert d["flips_needed_for_threshold"] == max(
        0, round(d["pbo"] * 70 - 0.2 * 70 + 0.499)
    )  # partitions that would have to turn good to reach 0.2
    assert set(d["sensitivity_to_block_count"]) == {
        4,
        6,
        8,
        10,
    }  # how fragile the number is to how the history is cut
    assert (
        len(d["distribution"]["logit_quantiles"]) == 5
        and d["distribution"]["winner_is_rank_mean"] > 0
    )


def test_it_refuses_input_it_cannot_cut_into_blocks():
    with pytest.raises(ValueError, match="at least 2"):
        pd.diagnose([noise(1)], ["a"], [f"b{i}" for i in range(8)])
