# ruff: noqa: E501
"""The daily boot sequence (docs: TODO 1.2 and 5.3). A restart always begins at INITIALIZING and reaches PAPER or LIVE only through
DATA_VALIDATION and READY, and READY only when every recovery check holds. Each check is a probe: a function returning (ok, why). A probe
that raises counts as failed, with its message. A HALTED platform is not restarted by a boot: only an operator clears it.
The real probes are built in scripts/platform_boot.py from the pieces that exist (data freshness, the Kite session, the OMS and paper
reconciliation, the order log loading); this module only runs the sequence and records every step."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import psycopg

from algo.platform_state import store
from algo.platform_state.machine import Checks, PlatformState, State, TransitionError


@dataclass(frozen=True)
class Probe:
    ok: bool
    why: str


@dataclass(frozen=True)
class Probes:
    market_data_fresh: Callable[[], Probe]
    broker_session_valid: Callable[[], Probe]
    orders_reconciled: Callable[[], Probe]
    positions_reconciled: Callable[[], Probe]
    cash_reconciled: Callable[[], Probe]
    portfolio_loaded: Callable[[], Probe]


@dataclass(frozen=True)
class BootResult:
    state: State
    failed: list[str]


def _run(name: str, probe: Callable[[], Probe]) -> Probe:
    try:
        return probe()
    except Exception as e:  # a probe that cannot answer has not passed
        return Probe(False, f"the probe raised: {e}")


def boot(
    conn: psycopg.Connection,
    now: datetime,
    probes: Probes,
    *,
    mode: State = State.PAPER,
    live_enabled: bool = False,
    operator: bool = False,
) -> BootResult:
    last = store.latest(conn)
    ps = PlatformState(live_enabled=live_enabled)
    if last is not None and last[0] is State.HALTED:
        if not operator:
            return BootResult(
                State.HALTED,
                ["the platform is HALTED: an operator must clear it before it can boot again"],
            )
        ps.state = State.HALTED
        ps.transition(State.RECOVERY, now, "an operator cleared the halt", operator=True)
        ps.transition(State.DATA_VALIDATION, now, "boot after an operator cleared the halt")
    else:
        ps.transition(State.DATA_VALIDATION, now, "boot")
    results = {name: _run(name, getattr(probes, name)) for name in Checks.__dataclass_fields__}
    failed = [f"{name}: {r.why}" for name, r in results.items() if not r.ok]
    if failed:
        ps.transition(State.RECOVERY, now, "recovery checks failed: " + "; ".join(failed))
        store.append(conn, ps.events, operator=operator)
        return BootResult(ps.state, failed)
    ps.transition(
        State.READY, now, "every recovery check passed", checks=Checks(**{n: True for n in results})
    )
    problems: list[str] = []
    try:
        ps.transition(mode, now, f"boot complete: {mode.value}")
    except TransitionError as e:
        problems.append(str(e))
    store.append(conn, ps.events, operator=operator)
    return BootResult(ps.state, problems)
