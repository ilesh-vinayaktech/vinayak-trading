# ruff: noqa: E501
"""Statistics for judging whether a backtest result is believable. Pure functions on lists of
period returns (floats are fine: these are statistics, not money).

* Sharpe, skew, kurtosis                       the moments the Sharpe test needs
* PSR  Probabilistic Sharpe Ratio              P(true SR > benchmark SR), given non-normal returns
* Expected max SR + DSR  Deflated Sharpe       PSR against the best Sharpe luck alone would give
                                               among N tried configs (Bailey & Lopez de Prado)
* max drawdown, stationary bootstrap CIs       uncertainty on Sharpe / drawdown
* PBO via CSCV                                 probability the in-sample winner underperforms OOS
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations
from statistics import NormalDist

EULER_GAMMA = 0.5772156649015329
TRADING_DAYS = 252
_N = NormalDist()


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def stdev(xs: Sequence[float]) -> float:
    """Sample standard deviation (n - 1)."""
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def sharpe_per_period(returns: Sequence[float]) -> float | None:
    """mean / stdev of the period returns; None when undefined (too short or no variation)."""
    if len(returns) < 2:
        return None
    sd = stdev(returns)
    return None if sd == 0 else mean(returns) / sd


def annualised_sharpe(returns: Sequence[float], periods: int = TRADING_DAYS) -> float | None:
    sr = sharpe_per_period(returns)
    return None if sr is None else sr * math.sqrt(periods)


def skew(returns: Sequence[float]) -> float:
    m = mean(returns)
    m2 = sum((x - m) ** 2 for x in returns) / len(returns)
    m3 = sum((x - m) ** 3 for x in returns) / len(returns)
    return float(m3 / m2**1.5)


def kurtosis(returns: Sequence[float]) -> float:
    """Non-excess kurtosis (a normal distribution is 3)."""
    m = mean(returns)
    m2 = sum((x - m) ** 2 for x in returns) / len(returns)
    m4 = sum((x - m) ** 4 for x in returns) / len(returns)
    return m4 / m2**2


def psr(sr: float, sr_benchmark: float, n: int, skewness: float, kurt: float) -> float:
    """Probabilistic Sharpe Ratio. All Sharpe ratios are PER PERIOD; n = number of observations."""
    if n < 2:
        raise ValueError("need at least 2 observations")
    variance = 1 - skewness * sr + (kurt - 1) / 4 * sr**2
    if variance <= 0:
        raise ValueError("Sharpe estimator variance is not positive for these moments")
    return _N.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(variance))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """The best per-period Sharpe pure luck is expected to produce among `n_trials` independent
    configurations whose Sharpe ratios have variance `sr_variance`."""
    if n_trials < 1:
        raise ValueError("n_trials must be at least 1")
    if sr_variance < 0:
        raise ValueError("variance cannot be negative")
    if n_trials == 1:
        return 0.0
    z1 = _N.inv_cdf(1 - 1 / n_trials)
    z2 = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(sr_variance) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(returns: Sequence[float], n_trials: int, sr_variance: float) -> float | None:
    """P(true Sharpe > what luck alone would give after `n_trials` attempts). None if undefined."""
    sr = sharpe_per_period(returns)
    if sr is None or len(returns) < 4:
        return None
    return psr(
        sr,
        expected_max_sharpe(n_trials, sr_variance),
        len(returns),
        skew(returns),
        kurtosis(returns),
    )


def max_drawdown(returns: Sequence[float]) -> float:
    """Worst peak-to-trough fall of the compounded curve, as a negative fraction (0 = none)."""
    equity = peak = 1.0
    worst = 0.0
    for r in returns:
        equity *= 1 + r
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1)
    return worst


def stationary_bootstrap(
    returns: Sequence[float], n_boot: int, mean_block: float, seed: int
) -> list[list[float]]:
    """Politis-Romano stationary bootstrap: resamples keep serial dependence by drawing blocks of
    random (geometric) length. Deterministic for a given seed."""
    if not returns:
        raise ValueError("nothing to resample")
    if mean_block < 1:
        raise ValueError("mean_block must be at least 1")
    rng, n, p = random.Random(seed), len(returns), 1 / mean_block
    out = []
    for _ in range(n_boot):
        idx, sample = rng.randrange(n), []
        for _ in range(n):
            sample.append(returns[idx])
            idx = rng.randrange(n) if rng.random() < p else (idx + 1) % n
        out.append(sample)
    return out


@dataclass(frozen=True)
class Interval:
    point: float
    low: float
    high: float


def bootstrap_interval(
    returns: Sequence[float],
    stat: Callable[[Sequence[float]], float | None],
    *,
    n_boot: int = 1000,
    mean_block: float = 10,
    confidence: float = 0.95,
    seed: int = 0,
) -> Interval | None:
    point = stat(returns)
    if point is None:
        return None
    draws = sorted(
        v
        for s in stationary_bootstrap(returns, n_boot, mean_block, seed)
        if (v := stat(s)) is not None
    )
    if not draws:
        return None
    lo, hi = (1 - confidence) / 2, 1 - (1 - confidence) / 2
    return Interval(point, draws[int(lo * (len(draws) - 1))], draws[int(hi * (len(draws) - 1))])


@dataclass(frozen=True)
class PBOResult:
    pbo: float  # fraction of splits where the in-sample winner ranked at or below the OOS median
    logits: tuple[float, ...]
    splits: int


def pbo_cscv(returns_by_strategy: Sequence[Sequence[float]], n_blocks: int = 8) -> PBOResult:
    """Probability of Backtest Overfitting by combinatorially symmetric cross-validation.
    `returns_by_strategy[k]` is strategy k's return series (all the same length). The history is cut
    into `n_blocks` blocks; for every choice of half the blocks as in-sample, the in-sample winner's
    rank among all strategies out-of-sample gives a logit; PBO = share of logits <= 0."""
    n = len(returns_by_strategy)
    if n < 2:
        raise ValueError("need at least 2 strategies")
    if n_blocks < 2 or n_blocks % 2:
        raise ValueError("n_blocks must be an even number >= 2")
    t = len(returns_by_strategy[0])
    if any(len(r) != t for r in returns_by_strategy):
        raise ValueError("all return series must have the same length")
    if t < n_blocks:
        raise ValueError("fewer observations than blocks")
    size = t // n_blocks
    blocks = [range(b * size, (b + 1) * size) for b in range(n_blocks)]

    def score(rows: list[int], k: int) -> float:
        s = sharpe_per_period([returns_by_strategy[k][i] for i in rows])
        return 0.0 if s is None else s

    logits = []
    for ins in combinations(range(n_blocks), n_blocks // 2):
        is_rows = [i for b in ins for i in blocks[b]]
        oos_rows = [i for b in range(n_blocks) if b not in ins for i in blocks[b]]
        is_scores = [score(is_rows, k) for k in range(n)]
        winner = is_scores.index(max(is_scores))
        oos_scores = [score(oos_rows, k) for k in range(n)]
        rank = 1 + sum(s < oos_scores[winner] for s in oos_scores)  # 1 = worst
        omega = rank / (n + 1)
        logits.append(math.log(omega / (1 - omega)))
    return PBOResult(sum(lg <= 0 for lg in logits) / len(logits), tuple(logits), len(logits))


def mean_pairwise_correlation(series: Sequence[Sequence[float]]) -> float | None:
    """The average correlation between every pair of equal-length series (None when there are fewer than two usable ones)."""
    usable = [list(x) for x in series if len(x) > 1 and stdev(list(x)) > 0]
    if len(usable) < 2 or len({len(x) for x in usable}) != 1:
        return None
    n, out = len(usable[0]), []
    for a, b in combinations(usable, 2):
        ma, mb = mean(a), mean(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / (n - 1)
        out.append(cov / (stdev(a) * stdev(b)))
    return mean(out)
