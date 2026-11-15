# ruff: noqa: E501
"""The only door to an LLM (docs/vti-alignment.md decision 5): optional, budgeted, payload-guarded and failure-isolated.

Callers: tests/unit/learning/test_ai_gateway.py; no production caller yet. User's instruction: "do as much as you can do yourself, keep taking things one by
one from @TODO.md and @plan.md ... keep things finishing with test". The provider is injected (a callable), so no network or key lives here.
  * Budget: 2,000,000 tokens a DAY (owner decision 2026-11-15; was 250,000 a month), enforced BEFORE the call (on the estimate) and the real usage booked after. A rupee
    cap is optional and OFF by default: the owner set no rupee figure for the daily budget (the earlier Rs 1,000 a month was for the old token budget).
  * Payload guard: raw market data and holdout results never leave. Forbidden key names (bars, ohlc, prices, holdout, ...) and any list of more than
    `MAX_SERIES` numbers are refused.
  * Isolation: a provider error, a refusal by the budget, or an output that fails its validator returns Outcome(ok=False); nothing is raised into trading code.
Nothing here is persisted yet: the Ledger is in memory; a table comes with the first real provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

MAX_SERIES = 20
FORBIDDEN_KEYS = frozenset(
    {
        "bars",
        "ohlc",
        "ohlcv",
        "prices",
        "candles",
        "holdout",
        "equity_curve",
        "returns",
        "positions",
        "orders",
        "api_key",
        "token",
    }
)


class PayloadRefused(ValueError):
    pass


@dataclass(frozen=True)
class Budget:
    tokens: int = 2_000_000  # per period (a day)
    rupees: Decimal | None = None  # per period; None = no rupee cap


@dataclass
class Ledger:
    """Insert-only usage by period (a day, '2026-11-15')."""

    rows: list[tuple[str, int, Decimal]] = field(default_factory=list)

    def book(self, period: str, tokens: int, rupees: Decimal) -> None:
        self.rows.append((period, tokens, rupees))

    def used(self, period: str) -> tuple[int, Decimal]:
        return (
            sum(t for m, t, _ in self.rows if m == period),
            sum((r for m, _, r in self.rows if m == period), Decimal(0)),
        )


@dataclass(frozen=True)
class Reply:
    text: str
    tokens: int
    rupees: Decimal


@dataclass(frozen=True)
class Outcome:
    ok: bool
    value: Any = None
    reason: str = ""


def guard(payload: Any, path: str = "payload") -> None:
    if isinstance(payload, dict):
        for k, v in payload.items():
            if str(k).lower() in FORBIDDEN_KEYS:
                raise PayloadRefused(f"{path}.{k}: this kind of data never goes to a model")
            guard(v, f"{path}.{k}")
    elif isinstance(payload, (list, tuple)):
        if len(payload) > MAX_SERIES and all(
            isinstance(x, (int, float, Decimal)) and not isinstance(x, bool) for x in payload
        ):
            raise PayloadRefused(
                f"{path}: a series of {len(payload)} numbers looks like market data (limit {MAX_SERIES})"
            )
        for i, v in enumerate(payload):
            guard(v, f"{path}[{i}]")


def ask(
    provider: Callable[[dict[str, Any]], Reply] | None,
    payload: dict[str, Any],
    *,
    ledger: Ledger,
    period: str,
    estimate_tokens: int,
    estimate_rupees: Decimal,
    validate: Callable[[str], Any],
    budget: Budget = Budget(),  # noqa: B008
) -> Outcome:
    if provider is None:
        return Outcome(False, reason="no provider configured")
    try:
        guard(payload)
    except PayloadRefused as e:
        return Outcome(False, reason=f"payload refused: {e}")
    tokens, rupees = ledger.used(period)
    if tokens + estimate_tokens > budget.tokens:
        return Outcome(
            False,
            reason=f"token budget: {tokens}+{estimate_tokens} would pass {budget.tokens} for {period}",
        )
    if budget.rupees is not None and rupees + estimate_rupees > budget.rupees:
        return Outcome(
            False,
            reason=f"rupee budget: {rupees}+{estimate_rupees} would pass {budget.rupees} for {period}",
        )
    try:
        reply = provider(payload)
    except Exception as e:  # isolation: nothing a provider does may reach trading
        return Outcome(False, reason=f"provider failed: {type(e).__name__}")
    ledger.book(
        period, reply.tokens, reply.rupees
    )  # booked even if the output is bad: it was paid for
    try:
        return Outcome(True, validate(reply.text))
    except Exception as e:
        return Outcome(False, reason=f"output rejected: {type(e).__name__}: {e}")
