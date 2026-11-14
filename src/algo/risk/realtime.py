# ruff: noqa: E501
"""Real-time and post-trade risk (spec section 11). `monitor` turns the live numbers into breaches, each naming the Failure
the FailurePolicy answers (halt the strategy, optionally flatten, alert); `post_trade` flags the slow signals (slippage
against the model, fill rate) for review. Tracking error against the backtest needs the weekly re-run and is not here."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from algo.risk.killswitch import Failure
from algo.risk.limits import Limits
from algo.risk.model import Side


@dataclass(frozen=True)
class Live:
    day_pnl: Decimal  # negative is a loss
    equity: Decimal
    peak_equity: Decimal
    data_age_s: Decimal | None  # seconds since the last fresh bar or quote; None = none seen
    broker_connected: bool


@dataclass(frozen=True)
class Breach:
    failure: Failure
    detail: str


def monitor(live: Live, limits: Limits) -> list[Breach]:
    out: list[Breach] = []
    if limits.max_daily_loss is not None and live.day_pnl <= -limits.max_daily_loss:
        out.append(
            Breach(
                Failure.DAILY_LOSS,
                f"today's loss {-live.day_pnl} has reached {limits.max_daily_loss}",
            )
        )
    if limits.max_drawdown is not None and live.peak_equity > 0:
        drawdown = (live.peak_equity - live.equity) / live.peak_equity
        if drawdown >= limits.max_drawdown:
            out.append(
                Breach(
                    Failure.DRAWDOWN,
                    f"equity is {drawdown:.2%} below its peak (limit {limits.max_drawdown:.2%})",
                )
            )
    if limits.max_data_age_s is not None and (
        live.data_age_s is None or live.data_age_s > limits.max_data_age_s
    ):
        out.append(
            Breach(
                Failure.DATA_STALE,
                f"no fresh data for {live.data_age_s} s (limit {limits.max_data_age_s})",
            )
        )
    if not live.broker_connected:
        out.append(Breach(Failure.BROKER_DOWN, "the broker connection is down"))
    return out


@dataclass(frozen=True)
class Fill:
    side: Side
    qty: int
    ref_price: Decimal  # the price the model assumed (decision price)
    price: Decimal  # the price it filled at


@dataclass(frozen=True)
class Flag:
    code: str
    detail: str


def post_trade(
    fills: list[Fill], *, ordered_qty: int, model_bps: Decimal, limits: Limits
) -> list[Flag]:
    out: list[Flag] = []
    filled = sum(f.qty for f in fills)
    if filled:
        # adverse slippage in basis points, volume-weighted: a buy filling above, or a sell below, the model price is positive
        bps = (
            sum(
                Decimal(f.qty) * (f.price - f.ref_price) / f.ref_price * f.side.sign * 10000
                for f in fills
            )
            / filled
        )
        if bps > model_bps * limits.slippage_tolerance:
            out.append(
                Flag("SLIPPAGE", f"realised {bps:.1f} bps against the model's {model_bps} bps")
            )
    if (
        limits.min_fill_rate is not None
        and ordered_qty > 0
        and Decimal(filled) / ordered_qty < limits.min_fill_rate
    ):
        out.append(
            Flag(
                "FILL_RATE",
                f"{filled} of {ordered_qty} shares filled, below {limits.min_fill_rate:.0%}",
            )
        )
    return out
