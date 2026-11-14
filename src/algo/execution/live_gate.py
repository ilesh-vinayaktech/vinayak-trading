# ruff: noqa: E501
"""Mode safety (spec section 11): live trading needs ALL of an explicit environment flag, a strategy in the LIVE lifecycle stage and a
valid broker session, and every required regulatory rule recorded and recently verified. Anything else is paper. A LiveGate is the proof the broker adapter asks for; without one it will not start."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class LiveRefused(Exception):
    pass


@dataclass(frozen=True)
class LiveGate:
    open: bool = False


def problems(
    env: Mapping[str, str], strategy_stage: str, session_valid: bool, regulatory: Sequence[str]
) -> list[str]:
    """`regulatory` is what `execution.regulatory.check` found: required rules not recorded or not verified lately. Required, so no caller can forget it."""
    out: list[str] = []
    if env.get("ALGO_LIVE") != "1":
        out.append("ALGO_LIVE=1 is not set")
    if strategy_stage != "LIVE":
        out.append(f"the strategy is in the {strategy_stage} stage, not the LIVE stage")
    if not session_valid:
        out.append("there is no valid broker session")
    return [*out, *regulatory]


def mode(
    env: Mapping[str, str], strategy_stage: str, session_valid: bool, regulatory: Sequence[str]
) -> str:
    return "PAPER" if problems(env, strategy_stage, session_valid, regulatory) else "LIVE"


def open_gate(
    env: Mapping[str, str], strategy_stage: str, session_valid: bool, regulatory: Sequence[str]
) -> LiveGate:
    found = problems(env, strategy_stage, session_valid, regulatory)
    if found:
        raise LiveRefused("live trading is refused: " + "; ".join(found))
    return LiveGate(open=True)
