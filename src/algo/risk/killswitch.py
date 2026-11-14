# ruff: noqa: E501
"""The kill switch (spec section 11): three distinct operations, global or per strategy.

  PAUSE    no new orders; nothing else changes
  CANCEL   PAUSE, and the OMS cancels every open order
  FLATTEN  CANCEL, and the OMS closes the positions (reduce-only orders); needs an explicit emergency override
Failures map to a mode through a FailurePolicy. Flatten is never automatic unless the policy says so AND
auto_flatten is switched on; without it a failure that asks for FLATTEN is answered with CANCEL. Resuming is always a
person's explicit act. This module only holds the state: the risk engine refuses orders by it, the OMS acts on it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Mode(StrEnum):
    RUNNING = "RUNNING"
    PAUSE = "PAUSE"
    CANCEL = "CANCEL"
    FLATTEN = "FLATTEN"

    @property
    def severity(self) -> int:
        return ("RUNNING", "PAUSE", "CANCEL", "FLATTEN").index(self.value)

    @property
    def blocks_new(self) -> bool:
        return self is not Mode.RUNNING

    @property
    def cancels_open(self) -> bool:
        return self in (Mode.CANCEL, Mode.FLATTEN)

    @property
    def closes_positions(self) -> bool:
        return self is Mode.FLATTEN


class Failure(StrEnum):
    DATA_STALE = "DATA_STALE"
    BROKER_DOWN = "BROKER_DOWN"
    DAILY_LOSS = "DAILY_LOSS"
    DRAWDOWN = "DRAWDOWN"
    EXECUTION_FAILURES = "EXECUTION_FAILURES"
    AMBIGUOUS_ORDER = "AMBIGUOUS_ORDER"
    RECONCILIATION = "RECONCILIATION"


class KillSwitchError(Exception):
    pass


@dataclass(frozen=True)
class FailurePolicy:
    actions: Mapping[Failure, Mode] = field(
        default_factory=dict
    )  # a failure not listed here pauses
    auto_flatten: bool = False

    def respond(self, failure: Failure) -> Mode:
        mode = self.actions.get(failure, Mode.PAUSE)
        if mode is Mode.FLATTEN and not self.auto_flatten:
            return Mode.CANCEL
        return mode


@dataclass(frozen=True)
class SwitchEvent:
    ts: datetime
    scope: str | None  # None: global; otherwise a strategy id
    mode: Mode
    by: str
    reason: str


class KillSwitch:
    def __init__(self) -> None:
        self._modes: dict[str | None, Mode] = {}
        self.events: list[SwitchEvent] = []

    def mode(self, strategy_id: str) -> Mode:
        a, b = self._modes.get(None, Mode.RUNNING), self._modes.get(strategy_id, Mode.RUNNING)
        return a if a.severity >= b.severity else b

    def _set(self, mode: Mode, scope: str | None, by: str, reason: str, now: datetime) -> None:
        self._modes[scope] = mode
        self.events.append(SwitchEvent(now, scope, mode, by, reason))

    def pause(self, scope: str | None, *, by: str, reason: str, now: datetime) -> None:
        self._set(Mode.PAUSE, scope, by, reason, now)

    def cancel(self, scope: str | None, *, by: str, reason: str, now: datetime) -> None:
        self._set(Mode.CANCEL, scope, by, reason, now)

    def flatten(
        self,
        scope: str | None,
        *,
        by: str,
        reason: str,
        now: datetime,
        emergency_override: bool = False,
    ) -> None:
        if not emergency_override:
            raise KillSwitchError("FLATTEN needs an explicit emergency override")
        self._set(Mode.FLATTEN, scope, by, reason, now)

    def resume(self, scope: str | None, *, by: str, reason: str, now: datetime) -> None:
        self._set(Mode.RUNNING, scope, by, reason, now)

    def apply(
        self, failure: Failure, policy: FailurePolicy, scope: str | None, now: datetime
    ) -> Mode:
        """Answer a failure by policy. Only ever escalates the scope's own mode; returns the mode now in force."""
        wanted = policy.respond(failure)
        current = self._modes.get(scope, Mode.RUNNING)
        if wanted.severity > current.severity:
            self._set(wanted, scope, f"policy:{failure.value}", failure.value, now)
            return wanted
        return current
