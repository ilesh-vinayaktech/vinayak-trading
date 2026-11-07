"""Audit of several benchmark series used together: date alignment, reconciliation of every
observation with the exchange-session evidence, discontinuities and anomaly overlap. Pure functions.

Evidence discipline: a benchmark value is NOT evidence that the exchange traded (that would be
circular). Independent trading evidence is an official bhavcopy for the day; independent closure
evidence is a holiday list or an absent bhavcopy. Where only the benchmark (or a calendar rule)
speaks, the outcome says so. Nothing is interpolated, dropped or reclassified silently."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from algo.core.calendar import SessionInfo
from algo.data.benchmark_compare import correlation, daily_returns

# outcomes for an OBSERVED benchmark date
CONFIRMED_REGULAR = "CONFIRMED_REGULAR"  # bhavcopy exists, weekday rule agrees
CONFIRMED_SPECIAL = "CONFIRMED_SPECIAL"  # bhavcopy exists on a listed special session
WEEKDAY_RULE_PROVISIONAL = "WEEKDAY_RULE_PROVISIONAL"  # weekday, no independent evidence
BENCHMARK_ONLY_SESSION = "BENCHMARK_ONLY_SESSION"  # listed session, evidence is the benchmark
QUARANTINED_UNRESOLVED = "QUARANTINED_UNRESOLVED"  # the bhavcopy is quarantined
INVESTIGATE = "INVESTIGATE"  # no known session for a day with a value
# outcomes for a date INSIDE a series' coverage that has no value
DATA_GAP = "DATA_GAP"  # a bhavcopy proves trading, the series has no value
ALIGNMENT_GAP = "ALIGNMENT_GAP"  # another series has a value that day
QUARANTINED_NO_VALUE = "QUARANTINED_NO_VALUE"
EXPECTED_CLOSED = "EXPECTED_CLOSED"  # holiday list or no bhavcopy published
EXPECTED_NO_SESSION = "EXPECTED_NO_SESSION"  # an ordinary weekend
UNCONFIRMED_NO_VALUE = "UNCONFIRMED_NO_VALUE"  # weekday, no value, no independent closure evidence
EXPECTED_CLOSED_INFERRED = "EXPECTED_CLOSED_INFERRED"  # no value; exchange files chain over the day
ARCHIVE_GAP_SESSION_LIKELY = (
    "ARCHIVE_GAP_SESSION_LIKELY"  # no value; exchange files imply a session
)


@dataclass(frozen=True)
class Evidence:
    traded: frozenset[date]  # official bhavcopy loaded
    not_published: frozenset[date]  # exchange published none
    quarantined: frozenset[date]  # a file exists but is unusable
    first: date  # range over which bhavcopies were requested
    last: date
    closed_inferred: frozenset[date] = frozenset()  # exchange files chain over the day (inferred)
    archive_gap: frozenset[date] = frozenset()  # exchange files imply a session, file missing


def observed_outcome(d: date, info: SessionInfo, ev: Evidence) -> tuple[str, str]:
    weekend = d.weekday() >= 5
    if d in ev.quarantined:
        return QUARANTINED_UNRESOLVED, "bhavcopy quarantined: trading is not independently shown"
    if d in ev.traded:
        if info.existence == "EVIDENCED":
            return CONFIRMED_SPECIAL, "bhavcopy exists; kind and hours remain as listed"
        if weekend or info.existence == "NONE":
            return INVESTIGATE, "bhavcopy exists on a day no session is listed"
        return CONFIRMED_REGULAR, "bhavcopy exists on a weekday session"
    if d in ev.closed_inferred or d in ev.archive_gap:
        return INVESTIGATE, "value on a day the exchange's own files show no confirmed session"
    if info.existence == "EVIDENCED":
        return BENCHMARK_ONLY_SESSION, "listed session; the only evidence is the benchmark itself"
    if weekend:
        return INVESTIGATE, "weekend value with no listed session"
    if info.existence == "NONE":
        return INVESTIGATE, "value on a known holiday"
    if ev.first <= d <= ev.last and d in ev.not_published:
        return INVESTIGATE, "weekday value but the exchange published no bhavcopy"
    return WEEKDAY_RULE_PROVISIONAL, "weekday; no independent holiday or trading evidence"


def missing_outcome(d: date, info: SessionInfo, ev: Evidence, elsewhere: bool) -> str:
    if d in ev.traded:
        return DATA_GAP
    if d in ev.quarantined:
        return QUARANTINED_NO_VALUE
    if elsewhere:
        return ALIGNMENT_GAP
    if d in ev.archive_gap:
        return ARCHIVE_GAP_SESSION_LIKELY
    if d in ev.closed_inferred:
        return EXPECTED_CLOSED_INFERRED
    if d in ev.not_published or info.existence == "NONE" and d.weekday() < 5:
        return EXPECTED_CLOSED
    if d.weekday() >= 5:
        return EXPECTED_NO_SESSION
    return UNCONFIRMED_NO_VALUE


@dataclass
class Reconciliation:
    observed: dict[date, tuple[str, str, tuple[str, ...]]]  # day -> outcome, reason, series
    observed_counts: dict[str, int]
    missing: dict[str, dict[str, list[date]]]  # series -> outcome -> dates (weekends only counted)
    missing_counts: dict[str, dict[str, int]]


def reconcile(
    series: Mapping[str, Mapping[date, Decimal]],
    info: Callable[[date], SessionInfo],
    ev: Evidence,
) -> Reconciliation:
    names = sorted(series)
    union = sorted({d for lv in series.values() for d in lv})
    obs: dict[date, tuple[str, str, tuple[str, ...]]] = {}
    counts: dict[str, int] = {}
    for d in union:
        outcome, why = observed_outcome(d, info(d), ev)
        obs[d] = (outcome, why, tuple(n for n in names if d in series[n]))
        counts[outcome] = counts.get(outcome, 0) + 1
    missing: dict[str, dict[str, list[date]]] = {}
    mcounts: dict[str, dict[str, int]] = {}
    for n in names:
        lv = series[n]
        lo, hi = min(lv), max(lv)
        missing[n], mcounts[n] = {}, {}
        d = lo
        while d <= hi:
            if d not in lv:
                other = any(d in series[m] for m in names if m != n)
                o = missing_outcome(d, info(d), ev, other)
                mcounts[n][o] = mcounts[n].get(o, 0) + 1
                if o != EXPECTED_NO_SESSION:  # ordinary weekends are only counted
                    missing[n].setdefault(o, []).append(d)
            d += timedelta(days=1)
    return Reconciliation(obs, counts, missing, mcounts)


def alignment(series: Mapping[str, Mapping[date, Decimal]]) -> dict[str, dict[str, object]]:
    """Per series: coverage, and every date of the union it lacks, split into dates OUTSIDE its own
    coverage (a coverage difference) and dates INSIDE it (a gap that another series fills)."""
    union = sorted({d for lv in series.values() for d in lv})
    out: dict[str, dict[str, object]] = {}
    for n in sorted(series):
        lv = series[n]
        lo, hi = min(lv), max(lv)
        outside = [d for d in union if d not in lv and not lo <= d <= hi]
        inside = [d for d in union if d not in lv and lo <= d <= hi]
        out[n] = {
            "first": lo, "last": hi, "observations": len(lv),
            "outside_coverage": len(outside),
            "outside_range": (outside[0], outside[-1]) if outside else None,
            "inside_gaps": inside,
        }  # fmt: skip
    return out


def discontinuities(
    series: Mapping[str, Mapping[date, Decimal]], threshold: Decimal = Decimal("0.05")
) -> list[dict[str, object]]:
    """Daily moves of at least `threshold`, each tested against the other series' own return that
    day: CORROBORATED (same sign, at least half the size), UNCORROBORATED_SINGLE_SERIES (nobody
    else has a return then) or UNEXPLAINED (others have one and disagree)."""
    rets = {n: daily_returns(lv) for n, lv in series.items()}
    out = []
    for n in sorted(series):
        for d, (_prev, r) in sorted(rets[n].items()):
            if abs(r) < float(threshold):
                continue
            others = {m: rets[m][d][1] for m in sorted(series) if m != n and d in rets[m]}
            agree = {m: x for m, x in others.items() if x * r > 0 and abs(x) >= abs(r) / 2}
            status = (
                "CORROBORATED" if agree
                else "UNCORROBORATED_SINGLE_SERIES" if not others else "UNEXPLAINED"
            )  # fmt: skip
            out.append({"series": n, "date": d, "return": r, "status": status,
                        "others": others})  # fmt: skip
    return out


def net_rises(
    gross: Mapping[date, Decimal], net: Mapping[date, Decimal], tol: Decimal = Decimal("0.00002")
) -> dict[date, float]:
    """Days the net/gross ratio rises by more than `tol` (relative), as validate_net defines it."""
    shared = sorted(d for d in net if d in gross)
    ratio = {d: net[d] / gross[d] for d in shared}
    return {
        b: float(ratio[b] / ratio[a] - 1)
        for a, b in zip(shared, shared[1:], strict=False)
        if ratio[b] - ratio[a] > tol * ratio[a]
    }


def ratio_changes(gross: Mapping[date, Decimal], net: Mapping[date, Decimal]) -> dict[date, float]:
    shared = sorted(d for d in net if d in gross)
    ratio = {d: net[d] / gross[d] for d in shared}
    return {b: float(ratio[b] / ratio[a] - 1) for a, b in zip(shared, shared[1:], strict=False)}


def anomaly_overlap(
    a: Mapping[date, float], b: Mapping[date, float], gain_a: Mapping[date, float],
    gain_b: Mapping[date, float], ex_dates: frozenset[date],
) -> dict[str, object]:  # fmt: skip
    """How two sets of 'less dividend-inclusive series gained' anomalies relate. `gain_*` are the
    daily gains over every comparable date of each pair. The overlap expected by chance is computed
    over the dates both pairs can be compared on; the verdict describes, it never names a cause."""
    common = sorted(set(gain_a) & set(gain_b))
    both = sorted(set(a) & set(b))
    chance = len(set(a) & set(common)) * len(set(b) & set(common)) / len(common) if common else 0.0
    corr = (
        correlation([gain_a[d] for d in common], [gain_b[d] for d in common])
        if len(common) > 2 else float("nan")
    )  # fmt: skip

    def ex_share(s: Mapping[date, float]) -> float:
        return sum(d in ex_dates for d in s) / len(s) if s else 0.0

    base = sum(d in ex_dates for d in common) / len(common) if common else 0.0
    above = len(both) > 2 * chance and len(both) >= 3
    return {
        "count_a": len(a), "count_b": len(b), "common_comparable_dates": len(common),
        "intersection": both, "expected_by_chance": chance,
        "magnitude_correlation_all_common_dates": corr,
        "ex_date_share_a": ex_share(a), "ex_date_share_b": ex_share(b),
        "ex_date_share_all_common_dates": base,
        "direction": "both are days on which the less dividend-inclusive series gains on the other",
        "verdict": "OVERLAP_ABOVE_CHANCE" if above else "NO_OVERLAP_BEYOND_CHANCE",
    }  # fmt: skip
