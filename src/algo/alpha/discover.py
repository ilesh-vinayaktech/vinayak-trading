# ruff: noqa: E501
"""Alpha discovery for one feature at one horizon (plan.md section 6): does the feature rank stocks by what they earn afterwards?

Pure: it is handed the feature values, the closes and the session list, and returns evidence. It reads no database and no clock.
  * Forward return. A feature known at the close of session t is acted on no earlier than the NEXT session, so the return is measured from the close of
    t+1 to the close of t+1+h. Using t's own close would credit the feature with a move it could not have traded.
  * The holdout. An observation whose return ends after `last_allowed` is dropped, so no number here depends on a price the research may not see.
  * A missing close at either end gives no return for that stock that day. Nothing is filled in.
Every result carries a hash of its own contents, so a rerun can be compared bit for bit."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from algo.alpha import stats

SIGNAL_DELAY = 1  # sessions between the feature's day and the close the return starts from


@dataclass(frozen=True)
class Evidence:
    feature: str
    version: str
    horizon: int
    days: int  # days that produced an IC
    avg_names: float  # stocks per day behind those ICs
    mean_ic: float | None
    std_ic: float | None
    icir: float | None
    hit_rate: float | None
    t_stat: float | None
    p_value: float | None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def overlap_lag(horizon: int) -> int:
    """Daily ICs of an h-session return share h - 1 sessions of price path with the next day's: that is the autocorrelation to correct for."""
    return horizon - 1


def forward_returns(
    closes: Mapping[int, Mapping[date, Decimal]],
    sessions: Sequence[date],
    horizon: int,
    last_allowed: date,
) -> dict[date, dict[int, float]]:
    """{signal day: {stock: return from the close SIGNAL_DELAY sessions later to the close `horizon` sessions after that}}."""
    out: dict[date, dict[int, float]] = {}
    for i, day in enumerate(sessions):
        start, end = i + SIGNAL_DELAY, i + SIGNAL_DELAY + horizon
        if end >= len(sessions) or sessions[end] > last_allowed:
            continue
        s, e = sessions[start], sessions[end]
        row = {
            iid: float(series[e] / series[s] - 1)
            for iid, series in closes.items()
            if s in series and e in series and series[s] > 0
        }
        out[day] = row
    return out


def evaluate(
    name: str,
    version: str,
    feature: Mapping[tuple[int, date], Decimal],
    closes: Mapping[int, Mapping[date, Decimal]],
    sessions: Sequence[date],
    *,
    horizon: int,
    last_allowed: date,
    min_names: int,
    eligible: Mapping[date, frozenset[int]] | None = None,
) -> Evidence:
    """`eligible`, when given, is the set of names that count on each day (for example the most liquid): the others are left out of that day's cross-section as if they did not exist."""
    fwd = forward_returns(closes, sessions, horizon, last_allowed)
    by_day: dict[date, dict[int, float]] = {}
    for (iid, day), value in feature.items():
        if eligible is not None and iid not in eligible.get(day, ()):
            continue
        by_day.setdefault(day, {})[iid] = float(value)
    ics: list[float] = []
    names = 0
    for day in sessions:
        if day not in fwd or day not in by_day:
            continue
        ic = stats.cross_sectional_ic(by_day[day], fwd[day], min_names=min_names)
        if ic is not None:
            ics.append(ic)
            names += len(set(by_day[day]) & set(fwd[day]))
    s = stats.summarise(ics, lag=overlap_lag(horizon))
    return Evidence(
        name,
        version,
        horizon,
        s.n,
        0.0 if not ics else names / len(ics),
        s.mean,
        s.std,
        s.icir,
        s.hit_rate,
        s.t_stat,
        s.p_value,
    )


def discover(
    features: Mapping[tuple[str, str], Mapping[tuple[int, date], Decimal]],
    closes: Mapping[int, Mapping[date, Decimal]],
    sessions: Sequence[date],
    *,
    horizons: Sequence[int],
    last_allowed: date,
    min_names: int,
    heartbeat: Callable[[str, int, int, int], None] | None = None,
    eligible: Mapping[date, frozenset[int]] | None = None,
) -> list[Evidence]:
    """Every feature at every horizon, in a stable order (feature name, version, horizon), so a rerun lists the same things in the same order. `heartbeat(feature, horizon, k, n)` is
    called before each one of the n tests, so a caller can show that a long run is working."""
    plan = [(name, version, h) for name, version in sorted(features) for h in sorted(horizons)]
    out: list[Evidence] = []
    for k, (name, version, h) in enumerate(plan, 1):
        if heartbeat:
            heartbeat(name, h, k, len(plan))
        out.append(
            evaluate(
                name,
                version,
                features[(name, version)],
                closes,
                sessions,
                horizon=h,
                last_allowed=last_allowed,
                min_names=min_names,
                eligible=eligible,
            )
        )
    return out
