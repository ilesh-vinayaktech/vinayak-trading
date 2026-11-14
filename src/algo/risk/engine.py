# ruff: noqa: E501
"""The risk engine: the kill switch, the pre-trade checks and the order-rate limit, in that order, as one decision.
Nothing reaches the broker unless `approve` says so. The engine keeps one thing of its own: the rate limiter's bucket."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from algo.risk.checks import check
from algo.risk.killswitch import KillSwitch, Mode
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Decision, Market, OrderRequest, Rejection


class TokenBucket:
    """`burst` orders at once, refilling at `rate_per_s`."""

    def __init__(self, rate_per_s: Decimal, burst: int, now: datetime) -> None:
        self.rate, self.burst = rate_per_s, Decimal(burst)
        self.tokens, self.last = Decimal(burst), now

    def take(self, now: datetime) -> bool:
        elapsed = Decimal((now - self.last) // timedelta(microseconds=1)) / 1_000_000  # exact
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class RiskEngine:
    def __init__(self, limits: Limits, switch: KillSwitch) -> None:
        self.limits, self.switch = limits, switch
        self._bucket: TokenBucket | None = None

    def approve(
        self, order: OrderRequest, market: Market, book: Book, day: Day, now: datetime
    ) -> Decision:
        rejections: list[Rejection] = []
        mode = self.switch.mode(order.strategy_id)
        if mode.blocks_new and not (order.reduce_only and mode is Mode.FLATTEN):
            rejections.append(
                Rejection("PAUSED", f"the kill switch is {mode.value} for {order.strategy_id}")
            )
        rejections += check(order, market, book, day, self.limits, now).rejections
        if not rejections and self.limits.order_rate_per_s is not None:
            if self._bucket is None:
                self._bucket = TokenBucket(
                    self.limits.order_rate_per_s, self.limits.order_burst, now
                )
            if not self._bucket.take(now):
                rejections.append(
                    Rejection("RATE", f"more than {self.limits.order_rate_per_s} orders a second")
                )
        return Decision(tuple(rejections))
