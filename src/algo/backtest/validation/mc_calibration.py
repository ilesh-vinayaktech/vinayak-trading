# ruff: noqa: E501
"""Holdout policy v3 section 2.2: the calibration of the Monte Carlo bootstrap test, and the primary-test power and full-policy pass probability.

Simulated daily returns r_t = m + s x_t over N = 460 sessions (500 discarded warm-up sessions for the recursive series); seven decision series and one drift diagnostic.
Randomness is keyed exactly as the policy says: one 128-bit root seed R; data of chunk c of series i from `SeedSequence(entropy=R, spawn_key=(i, c, 0))`, all of a chunk's draws in
the fixed order written in `simulate`; dataset j's bootstrap seed `SeedSequence(entropy=R, spawn_key=(i, c, 1, j))` (its draw blocks add one more key). A chunk's result depends only on
its keys, so a stopped run resumes at the next unfinished chunk and gives the same answer. Chunk results are stored as JSON beside their keys."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from algo.backtest.validation import mc_bootstrap as mc

N = 460  # sessions in the holdout
WARM = 500
S_STRAT = 0.01
S_INDEX = 0.012
SR_INDEX = 0.5
RHO = 0.7
SERIES = (
    "normal",
    "ar1_0.1",
    "ar1_0.2",
    "student_t",
    "skew_normal",
    "garch",
    "regime",
)  # numbered 0-6 in this order
DRIFT_SERIES = 7  # the regime-dependent-drift diagnostic
DELTA = -0.9727
VOL = (0.525, 1.313)
STAY = 0.99
ALPHA_C = 0.05 / 30
CHUNK = 1000
DRAWS = 20_000  # per dataset in the calibration: the rule is valid for every B, so a smaller B tests the same procedure
DRIFT_GAP = 0.0015
Array = NDArray[np.float64]


def _ar(z: Array, phi: float) -> Array:
    out = np.empty_like(z)
    x: Any = np.zeros(z.shape[0])
    c = math.sqrt(1 - phi * phi)
    for t in range(z.shape[1]):
        x = phi * x + c * z[:, t]
        out[:, t] = x
    return out


def _garch(z: Array) -> Array:
    out = np.empty_like(z)
    h: Any = np.ones(z.shape[0])
    x: Any = np.zeros(z.shape[0])
    for t in range(z.shape[1]):
        h = 0.05 + 0.08 * x * x + 0.87 * h
        x = np.sqrt(h) * z[:, t]
        out[:, t] = x
    return out


def _regime(rng: np.random.Generator, k: int, t: int) -> Array:
    """State of each session (0 calm, 1 volatile): start from the stationary distribution, switch with probability 1 - STAY; the draws are s0 then u."""
    s: Any = (rng.random(k) < 0.5).astype(np.float64)
    u = rng.random((k, t))
    out = np.empty((k, t))
    for j in range(t):
        s = np.where(u[:, j] < 1 - STAY, 1 - s, s)
        out[:, j] = s
    return out


def _skew(u0: Array, z: Array) -> Array:
    mean, sd = DELTA * math.sqrt(2 / math.pi), math.sqrt(1 - 2 * DELTA * DELTA / math.pi)
    return (DELTA * np.abs(u0) + math.sqrt(1 - DELTA * DELTA) * z - mean) / sd


def simulate(series: int, rng: np.random.Generator, k: int, sharpe: float) -> tuple[Array, Array]:
    """k datasets of N strategy returns and the jointly simulated index returns. Draw order, fixed: z, w (standard normals, k x (WARM+N)), then what the series needs:
    student_t chi-square V (4 d.f.); skew_normal U0; regime s0 and u (inside `_regime`). The index uses zI = RHO z + sqrt(1 - RHO^2) w."""
    t = WARM + N
    z = rng.standard_normal((k, t))
    w = rng.standard_normal((k, t))
    zi = RHO * z + math.sqrt(1 - RHO * RHO) * w
    if series == 0:
        x, xi = z, zi
    elif series in (1, 2):
        phi = 0.1 if series == 1 else 0.2
        x, xi = _ar(z, phi), _ar(zi, phi)
    elif series == 3:
        v = rng.chisquare(4, (k, t))
        d = np.sqrt(v / 4) * math.sqrt(2)
        x, xi = z / d, zi / d
    elif series == 4:
        u0 = rng.standard_normal((k, t))
        x, xi = _skew(u0, z), _skew(u0, zi)
    elif series == 5:
        x, xi = _garch(z), _garch(zi)
    elif series in (6, DRIFT_SERIES):
        s = _regime(rng, k, t)
        vol = np.where(s == 1, VOL[1], VOL[0])
        x, xi = vol * z, vol * zi
        if series == DRIFT_SERIES:
            sig = math.sqrt(
                S_STRAT**2 * (VOL[0] ** 2 + VOL[1] ** 2) / 2 + (DRIFT_GAP / 2) ** 2
            )  # exact unconditional sd of the two-state mixture
            m_calm = sharpe * sig / math.sqrt(252) + DRIFT_GAP / 2
            drift = np.where(s == 1, m_calm - DRIFT_GAP, m_calm)
            return (drift + S_STRAT * x)[:, WARM:], (
                SR_INDEX * S_INDEX / math.sqrt(252) + S_INDEX * xi
            )[:, WARM:]
    else:
        raise ValueError(f"no series {series}")
    r = sharpe * S_STRAT / math.sqrt(252) + S_STRAT * x
    ri = SR_INDEX * S_INDEX / math.sqrt(252) + S_INDEX * xi
    return r[:, WARM:], ri[:, WARM:]


def _sharpe(r: Array) -> Array:
    return np.asarray(r.mean(axis=1) / r.std(axis=1, ddof=1) * math.sqrt(252))


def _max_dd(r: Array) -> Array:
    eq = np.cumprod(1 + r, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((r.shape[0], 1)), eq], axis=1), axis=1)[
        :, 1:
    ]
    return np.asarray(np.abs((eq / peak - 1).min(axis=1)))


def run_chunk(
    root: int, series: int, chunk: int, sharpe: float, datasets: int = CHUNK, draws: int = DRAWS
) -> dict[str, Any]:
    """One chunk: every dataset through the final decision procedure. Returns counts (and the floors for the full-policy pass probability)."""
    rng = np.random.Generator(
        np.random.PCG64(np.random.SeedSequence(entropy=root, spawn_key=(series, chunk, 0)))
    )
    r, ri = simulate(series, rng, datasets, sharpe)
    ks = np.array(
        [mc.test(r[j], root, draws, prefix=(series, chunk, 1, j)).k for j in range(datasets)]
    )
    p = (ks + 1) / (draws + 1)
    sh, dd, ddi = _sharpe(r), _max_dd(r), _max_dd(ri)
    floors = (sh >= 0.8) & (ddi > 0) & (dd <= 1.25 * ddi + 1e-9) & (sh - _sharpe(ri) >= 0.2)
    rej = p <= ALPHA_C
    corr = [
        float(np.corrcoef(r[j], ri[j])[0, 1]) for j in range(0, datasets, max(1, datasets // 50))
    ]
    return {
        "series": series, "chunk": chunk, "sharpe": sharpe, "datasets": datasets, "draws": draws,
        "rej_5": int((p <= 0.05).sum()), "rej_1": int((p <= 0.01).sum()), "rej_c": int(rej.sum()),
        "floors": int(floors.sum()), "full_pass": int((rej & floors).sum()), "corr_mean": float(np.mean(corr)),
    }  # fmt: skip


def _task(args: tuple[int, int, int, float, int, int, str]) -> str:
    root, series, chunk, sharpe, datasets, draws, out = args
    path = Path(out) / f"s{series}_sr{sharpe}_c{chunk}.json"
    if path.exists():  # a stopped run resumes at the next unfinished chunk
        return str(path)
    res = run_chunk(root, series, chunk, sharpe, datasets, draws)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"root": f"{root:032x}", **res}))
    tmp.rename(path)
    return str(path)


def run(
    root: int,
    out: Path,
    series: Iterable[int],
    chunks: int,
    sharpe: float = 0.0,
    datasets: int = CHUNK,
    draws: int = DRAWS,
    workers: int = 12,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Run `chunks` chunks of every given series with a pool of processes (about 200 MB each); finished chunks are skipped."""
    out.mkdir(parents=True, exist_ok=True)
    tasks = [(root, s, c, sharpe, datasets, draws, str(out)) for s in series for c in range(chunks)]
    with ProcessPoolExecutor(workers) as pool:
        for i, _ in enumerate(pool.map(_task, tasks), 1):
            if progress:
                progress(i, len(tasks))


def totals(out: Path, series: int, sharpe: float = 0.0) -> dict[str, float]:
    """Sum the stored chunks of one series at one true Sharpe."""
    keys = ("datasets", "rej_5", "rej_1", "rej_c", "floors", "full_pass")
    acc = dict.fromkeys(keys, 0)
    corr, n = 0.0, 0
    for f in sorted(out.glob(f"s{series}_sr{sharpe}_c*.json")):
        d = json.loads(f.read_text())
        for k in keys:
            acc[k] += d[k]
        corr, n = corr + d["corr_mean"], n + 1
    return {**acc, "chunks": n, "corr_mean": corr / n if n else float("nan")}


# ---- the exact binomial decision rules ------------------------------------------------------------------------------------------------------


def _logpmf(k: int, n: int, p: float) -> float:
    return (
        math.lgamma(n + 1)
        - math.lgamma(k + 1)
        - math.lgamma(n - k + 1)
        + k * math.log(p)
        + (n - k) * math.log1p(-p)
    )


def upper_tail(c: int, n: int, p: float) -> float:
    """Exact P(Binomial(n, p) >= c)."""
    total, k = 0.0, c
    while k <= n:
        term = math.exp(_logpmf(k, n, p))
        total += term
        if term < 1e-18 * max(total, 1e-300) and k > n * p:
            break
        k += 1
    return min(total, 1.0)


def boundary(n: int, p: float, alpha: float) -> int:
    """The smallest count c with exact P(Binomial(n, p) >= c) <= alpha: a series fails calibration at c or more rejections."""
    c = max(0, int(n * p))
    while upper_tail(c, n, p) > alpha:
        c += 1
    while c > 0 and upper_tail(c - 1, n, p) <= alpha:
        c -= 1
    return c


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Exact two-sided interval for a rate, by bisection on the binomial tails."""
    a = (1 - conf) / 2

    def bisect(f: Callable[[float], bool]) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) else (lo, mid)
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else bisect(lambda p: upper_tail(k, n, p) < a)
    upper = 1.0 if k == n else bisect(lambda p: 1 - upper_tail(k + 1, n, p) > a)
    return lower, upper


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def report(out: Path, datasets: int = 310_000) -> dict[str, Any]:
    """The calibration verdict: 7 decision checks at 0.1667% against the exact boundary (family bound 0.05), 14 diagnostics at 5% and 1%, and the 3 drift checks (0, -0.5, -1.0) against 1/600."""
    nominal = 1 / 600
    c7, c3 = boundary(datasets, nominal, 0.05 / 7), boundary(datasets, nominal, 0.05 / 3)
    decision, diagnostic, drift = [], [], []
    for i, name in enumerate(SERIES):
        t = totals(out, i)
        decision.append(
            {
                "series": name,
                "rejections": t["rej_c"],
                "datasets": t["datasets"],
                "fails_at": c7,
                "fail": t["rej_c"] >= c7 and t["datasets"] == datasets,
            }
        )
        for level, key, rate in (("5%", "rej_5", 0.05), ("1%", "rej_1", 0.01)):
            diagnostic.append({
                "series": name, "level": level, "rejections": t[key], "datasets": t["datasets"], "p_excess": upper_tail(int(t[key]), int(t["datasets"]), rate) if t["datasets"] else None,
                "wilson": wilson(int(t[key]), int(t["datasets"])) if t["datasets"] else None,
            })  # fmt: skip
    for sr in (0.0, -0.5, -1.0):
        t = totals(out, DRIFT_SERIES, sr)
        lo_hi = clopper_pearson(int(t["rej_c"]), int(t["datasets"])) if t["datasets"] else None
        drift.append(
            {
                "sharpe": sr,
                "rejections": t["rej_c"],
                "datasets": t["datasets"],
                "fails_at": c3,
                "fail": t["rej_c"] >= c3 and t["datasets"] == datasets,
                "clopper_pearson": lo_hi,
            }
        )
    return {
        "datasets_per_series": datasets, "decision": decision, "diagnostic": diagnostic, "drift": drift,
        "calibration_failed": any(d["fail"] for d in decision) or any(d["fail"] for d in drift),
        "complete": all(d["datasets"] == datasets for d in decision) and all(d["datasets"] == datasets for d in drift),
    }  # fmt: skip
