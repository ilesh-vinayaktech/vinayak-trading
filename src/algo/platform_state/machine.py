"""Platform trading state machine. Hard invariant: targets/orders only in PAPER or LIVE,
and PAPER/LIVE are reachable only through READY, which is reachable only after recovery checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from algo.core.clock import require_utc


class State(StrEnum):
    INITIALIZING = "INITIALIZING"
    DATA_VALIDATION = "DATA_VALIDATION"
    READY = "READY"
    PAPER = "PAPER"
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    RECOVERY = "RECOVERY"


S = State
ALLOWED: dict[State, frozenset[State]] = {
    S.INITIALIZING: frozenset({S.DATA_VALIDATION, S.HALTED}),
    S.DATA_VALIDATION: frozenset({S.READY, S.HALTED, S.RECOVERY}),
    S.READY: frozenset({S.PAPER, S.LIVE, S.HALTED, S.RECOVERY}),
    S.PAPER: frozenset({S.DEGRADED, S.HALTED, S.RECOVERY, S.READY}),
    S.LIVE: frozenset({S.DEGRADED, S.HALTED, S.RECOVERY, S.READY}),
    S.DEGRADED: frozenset({S.HALTED, S.RECOVERY}),
    S.HALTED: frozenset({S.RECOVERY}),
    S.RECOVERY: frozenset({S.DATA_VALIDATION, S.READY, S.HALTED}),
}
TRADING = frozenset({S.PAPER, S.LIVE})


class TransitionError(Exception):
    pass


@dataclass(frozen=True)
class Checks:
    """Recovery checks that must all hold before entering READY."""

    market_data_fresh: bool = False
    broker_session_valid: bool = False
    orders_reconciled: bool = False
    positions_reconciled: bool = False
    cash_reconciled: bool = False
    portfolio_loaded: bool = False

    def ok(self) -> bool:
        return all(self.__dict__.values())


@dataclass(frozen=True)
class StateEvent:
    ts: datetime
    from_state: State
    to_state: State
    reason: str


class PlatformState:
    """Append-only event log + current state. Boots in INITIALIZING, so a restart never trades."""

    def __init__(self, *, live_enabled: bool = False) -> None:
        self.state = State.INITIALIZING
        self.live_enabled = live_enabled
        self.events: list[StateEvent] = []

    def can_emit_targets(self) -> bool:
        return self.state in TRADING

    def transition(
        self,
        to: State,
        now: datetime,
        reason: str,
        *,
        checks: Checks | None = None,
        operator: bool = False,
    ) -> None:
        ts = require_utc(now)
        if to not in ALLOWED[self.state]:
            raise TransitionError(f"{self.state} -> {to} not allowed")
        if to is State.READY and self.state in {State.DATA_VALIDATION, State.RECOVERY}:
            if checks is None or not checks.ok():
                raise TransitionError("recovery checks not satisfied")
        if to is State.LIVE and not self.live_enabled:
            raise TransitionError("live not enabled")
        if self.state is State.HALTED and not operator:
            raise TransitionError("leaving HALTED requires operator action")
        self.events.append(StateEvent(ts, self.state, to, reason))
        self.state = to
