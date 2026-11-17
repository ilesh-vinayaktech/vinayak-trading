# ruff: noqa: E501
"""Holdout policy v3 section 2: the Monte Carlo stationary-bootstrap test of "true annualised Sharpe <= 0".

One vectorised NumPy implementation, used for calibration and for the holdout. Draws come in fixed blocks of BLOCK_DRAWS; block b has its own stream
`Generator(PCG64(SeedSequence(entropy=seed, spawn_key=(b,))))` and consumes it in a fixed order whatever the data, so a result never depends on how many blocks
are processed at once. Only the running exceedance count is kept. NumPy is pinned: Generator method algorithms may change between versions."""

import math
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

BLOCK_DRAWS = 10_000
RESTART = 1 / 21  # mean block of 21 sessions: the platform's BOOTSTRAP_MEAN_BLOCK
TRADING_DAYS = 252
ROWS = 256  # rows processed at a time inside a block; any value gives the same result


def new_seed() -> int:
    """128 bits from the operating system's random source; generated at batch freeze and never replaced."""
    return secrets.randbits(128)


def indices(starts: NDArray[Any], u: NDArray[Any], jumps: NDArray[Any], n: int) -> NDArray[Any]:
    """Politis-Romano indices: position 0 is `starts`; position j >= 1 restarts at jumps[j-1] when u[j-1] < RESTART, else previous + 1 modulo n.
    Each restart is packed as (position << 15 | index) so one running maximum finds the latest restart and its index together (n must be below 2**15)."""
    if n >= 1 << 15:
        raise ValueError("too many sessions for the packed form")
    d = starts.shape[0]
    cols = np.arange(n, dtype=np.int32)
    key = np.zeros((d, n), dtype=np.int32)
    key[:, 0] = starts
    key[:, 1:] = np.where(u < RESTART, (cols[1:] << 15) | jumps, 0)
    np.maximum.accumulate(key, axis=1, out=key)
    out: NDArray[Any] = (key & 0x7FFF) + (cols - (key >> 15))
    out -= n * (out >= n)
    return out


def block_draws(
    seed: int, block: int, n: int, d: int = BLOCK_DRAWS, prefix: tuple[int, ...] = ()
) -> tuple[NDArray[Any], NDArray[Any], NDArray[Any]]:
    """The three draws of one block (starts, u, jumps), in this order and with these dtypes, every time: the stream is fixed whatever is done with it."""
    rng = np.random.Generator(
        np.random.PCG64(np.random.SeedSequence(entropy=seed, spawn_key=(*prefix, block)))
    )
    starts = rng.integers(0, n, size=d, dtype=np.int32)
    u = rng.random(size=(d, n - 1))
    jumps = rng.integers(0, n, size=(d, n - 1), dtype=np.int32)
    return starts, u, jumps


def block_indices(
    seed: int, block: int, n: int, d: int = BLOCK_DRAWS, prefix: tuple[int, ...] = ()
) -> NDArray[Any]:
    """The whole index matrix of one draw block."""
    return indices(*block_draws(seed, block, n, d, prefix), n)


def sharpe_rows(y: NDArray[Any]) -> NDArray[Any]:
    """Annualised Sharpe of each row, sample standard deviation (n - 1) as in `stats.annualised_sharpe`; a zero-variance row is +inf (counts as an exceedance)."""
    sd = y.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = y.mean(axis=1) / sd * math.sqrt(TRADING_DAYS)
    return np.where(sd == 0, np.inf, out)


def p_mc(k: int, draws: int) -> float:
    return (k + 1) / (draws + 1)


def rejects(k: int, draws: int, alpha: float) -> bool:
    return p_mc(k, draws) <= alpha


@dataclass(frozen=True)
class Result:
    observed: float
    k: int
    draws: int

    @property
    def p(self) -> float:
        return p_mc(self.k, self.draws)


def test(
    returns: Sequence[float],
    seed: int,
    draws: int = 1_000_000,
    rows: int = ROWS,
    prefix: tuple[int, ...] = (),
) -> Result:
    """H0: true annualised Sharpe <= 0. Statistic: the observed Sharpe of the raw returns; null series: the returns with their sample mean removed."""
    r = np.asarray(returns, dtype=np.float64)
    n = r.shape[0]
    if n < 2:
        raise ValueError("at least 2 returns are needed")
    if not np.isfinite(r).all():
        raise ValueError("returns must be finite and complete")
    if draws % BLOCK_DRAWS:
        raise ValueError(f"draws must be a multiple of {BLOCK_DRAWS}")
    sd = r.std(ddof=1)
    if sd == 0:
        raise ValueError("returns have no variation")
    observed = float(r.mean() / sd * math.sqrt(TRADING_DAYS))
    y = r - r.mean()
    k = 0
    for b in range(draws // BLOCK_DRAWS):
        starts, u, jumps = block_draws(seed, b, n, prefix=prefix)
        for lo in range(
            0, BLOCK_DRAWS, rows
        ):  # slices that fit the cache: the same indices and statistics, far less memory traffic
            idx = indices(starts[lo : lo + rows], u[lo : lo + rows], jumps[lo : lo + rows], n)
            k += int((sharpe_rows(y[idx]) >= observed).sum())
    return Result(observed, k, draws)
