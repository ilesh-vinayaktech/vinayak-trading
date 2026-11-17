# ruff: noqa: E501
"""The swing score (TODO 6.2): one 0 to 100 number per stock, built from the screener fields, with every part kept so the screen can say why.

Each stock is ranked (a percentile) against the other stocks on a set of signals, signals are averaged into four components, and the components are combined
with fixed weights, tuned for days to weeks:
  trend           1 and 3-month change, price against its 50-day average, nearness to the 52-week high, ADX               (35%)
  participation   volume against its norm, delivery % against its norm, delivery %                                     (20%)
  smart_money     net bulk/block buying, insider net buying, change in FII, DII and promoter holding                    (30%)
  quality         ROE, ROCE, profit growth, low debt                                                                    (15%)
A missing figure is NEVER read as zero: a stock is ranked on a signal only among stocks that have it, a component with no signals is None, and the
composite is re-weighted over the components that exist (and needs at least three, else None). The weights are a starting point, not a finding: whether
the score predicts anything is for the prediction loop (TODO 6.5) and the study gates to say. Setup flags (breakout, accumulation, distribution, overbought,
weak trend) and the top reasons are added. Stocks trading under 5 crore a day, or with no turnover figure, are left out of the ranking and get no score. Pure: rows in, scores out; the input is not changed."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from algo.market.zone import pct_rank

COMPONENTS = ("trend", "participation", "smart_money", "quality")
WEIGHTS = {"trend": 0.35, "participation": 0.20, "smart_money": 0.30, "quality": 0.15}
MIN_COMPONENTS = 3
MIN_TURNOVER_CR = 5.0  # a stock trading under 5 crore a day (20-day average), or with no turnover figure, is not tradable at size: it neither gets a score nor is ranked against
REASON_RANK = 80  # a signal this high (a percentile) is worth naming

# component -> (field, higher is better, phrase used when it is a reason)
SIGNALS: dict[str, tuple[tuple[str, bool, str], ...]] = {
    "trend": (
        ("chg_1m", True, "Rising over 1 month"),
        ("chg_3m", True, "Rising over 3 months"),
        ("price_vs_sma50", True, "Well above its 50-day average"),
        ("pct_from_52w_high", True, "Near its 52-week high"),
        ("adx_14", True, "Strong trend (ADX)"),
    ),
    "participation": (
        ("volume_ratio", True, "Volume well above normal"),
        ("delivery_vs_avg", True, "Delivery % above its norm"),
        ("delivery_pct", True, "High delivery %"),
    ),
    "smart_money": (
        ("deal_net_30d", True, "Net bulk and block buying"),
        ("insider_net_90d", True, "Insiders buying"),
        ("fii_change", True, "FII holding rising"),
        ("dii_change", True, "DII holding rising"),
        ("promoter_change", True, "Promoter holding rising"),
    ),
    "quality": (
        ("roe", True, "High return on equity"),
        ("roce", True, "High return on capital"),
        ("profit_growth", True, "Profits growing"),
        ("debt_to_equity", False, "Low debt"),
    ),
}


@dataclass(frozen=True)
class Scored:
    instrument_id: int
    composite: float | None
    components: dict[str, float | None]
    flags: list[str]
    reasons: list[str]


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        return None
    return float(v)


def _positive(r: Mapping[str, Any], key: str) -> bool:
    v = _num(r.get(key))
    return v is not None and v > 0


def _negative(r: Mapping[str, Any], key: str) -> bool:
    v = _num(r.get(key))
    return v is not None and v < 0


def _tradable(r: Mapping[str, Any]) -> bool:
    """A known turnover of at least MIN_TURNOVER_CR; a stock whose liquidity we cannot see is not scored (we would not know whether it can be traded)."""
    t = _num(r.get("turnover_cr"))
    return t is not None and t >= MIN_TURNOVER_CR


def _flags(r: Mapping[str, Any]) -> list[str]:
    near, vol, deliv = (
        _num(r.get("pct_from_52w_high")),
        _num(r.get("volume_ratio")),
        _num(r.get("delivery_vs_avg")),
    )
    above, chg3, rsi = _num(r.get("price_vs_sma50")), _num(r.get("chg_3m")), _num(r.get("rsi_14"))
    money = ("deal_net_30d", "insider_net_90d", "fii_change", "dii_change")
    out: list[str] = []
    if (
        near is not None
        and near >= -3
        and vol is not None
        and vol >= 1.5
        and above is not None
        and above > 0
        and (deliv is None or deliv >= 1.2)
    ):
        out.append("Breakout setup")
    if sum(_positive(r, k) for k in money) >= 2:
        out.append("Accumulation")
    if sum(_negative(r, k) for k in money) >= 2:
        out.append("Distribution")
    if rsi is not None and rsi >= 75:
        out.append("Overbought")
    if above is not None and above < 0 and chg3 is not None and chg3 < 0:
        out.append("Weak trend")
    return out


def attach(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same rows with the score fields added (`score`, `score_<component>`, `setup`, `score_why`); a figure that does not exist is left out, never zero."""
    out = []
    for r, s in zip(rows, score_universe(rows), strict=True):
        extra: dict[str, Any] = {}
        if s.composite is not None:
            extra["score"] = Decimal(str(round(s.composite, 1)))
        for comp, v in s.components.items():
            if v is not None:
                extra[f"score_{comp}"] = Decimal(str(round(v, 1)))
        if s.flags:
            extra["setup"] = ", ".join(s.flags)
        if s.reasons:
            extra["score_why"] = "; ".join(s.reasons)
        out.append({**r, **extra})
    return out


def score_universe(rows: Sequence[Mapping[str, Any]]) -> list[Scored]:
    """One `Scored` per row, in the order given. Each row needs an `instrument_id`."""
    liquid = [_tradable(r) for r in rows]
    pools: dict[str, list[float]] = {}  # per signal: the values of every tradable stock that has it
    for signals in SIGNALS.values():
        for field, _, _ in signals:
            pools[field] = [
                v
                for r, ok in zip(rows, liquid, strict=True)
                if ok and (v := _num(r.get(field))) is not None
            ]
    out: list[Scored] = []
    for r, ok in zip(rows, liquid, strict=True):
        if not ok:
            out.append(Scored(int(r["instrument_id"]), None, dict.fromkeys(COMPONENTS), [], []))
            continue
        components: dict[str, float | None] = {}
        ranked: list[tuple[float, str]] = []
        for comp, signals in SIGNALS.items():
            ranks = []
            for field, higher, phrase in signals:
                v = _num(r.get(field))
                if v is None:
                    continue
                rank = pct_rank(pools[field], v)
                rank = rank if higher else 100.0 - rank
                ranks.append(rank)
                ranked.append((rank, phrase))
            components[comp] = sum(ranks) / len(ranks) if ranks else None
        have = {c: v for c, v in components.items() if v is not None}
        composite = None
        if len(have) >= MIN_COMPONENTS:
            weight = sum(WEIGHTS[c] for c in have)
            composite = sum(WEIGHTS[c] * v for c, v in have.items()) / weight
        reasons = [p for rank, p in sorted(ranked, key=lambda t: -t[0]) if rank >= REASON_RANK][:3]
        out.append(Scored(int(r["instrument_id"]), composite, components, _flags(r), reasons))
    return out
