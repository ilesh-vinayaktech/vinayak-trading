# ruff: noqa: E501
"""Pre-trade checks (spec section 11): one pure function, every breach reported with its reason.

A reduce-only order (closing or shrinking a position, what a flatten sends) is checked for what it is allowed to
be (instrument, hours, size, price band) and must really reduce the position, but it is exempt from exposure,
margin and daily limits: refusing to close a position because the day went badly would only add risk."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Decision, Market, OrderRequest, Rejection, Side

IST = ZoneInfo("Asia/Kolkata")


def check(
    order: OrderRequest, market: Market, book: Book, day: Day, limits: Limits, now: datetime
) -> Decision:
    out: list[Rejection] = []

    def reject(code: str, detail: str) -> None:
        out.append(Rejection(code, detail))

    price = order.price if order.price is not None else market.ltp
    value = price * order.qty
    delta = value * order.side.sign
    if order.qty <= 0:
        reject("BAD_QTY", f"quantity {order.qty} is not positive")
    if order.instrument_id in limits.restricted:
        reject("RESTRICTED", f"instrument {order.instrument_id} is restricted")
    if limits.allowed is not None and order.instrument_id not in limits.allowed:
        reject("NOT_ALLOWED", f"instrument {order.instrument_id} is not on the allow-list")
    if not market.tradable:
        reject("NOT_TRADABLE", "the instrument is not tradable now (expired, suspended or halted)")
    if limits.trading_hours is not None:
        t = now.astimezone(IST).time()
        if not limits.trading_hours[0] <= t <= limits.trading_hours[1]:
            reject(
                "HOURS",
                f"{t:%H:%M} IST is outside {limits.trading_hours[0]:%H:%M}-{limits.trading_hours[1]:%H:%M}",
            )
    if limits.max_order_qty is not None and order.qty > limits.max_order_qty:
        reject("MAX_QTY", f"{order.qty} shares is over {limits.max_order_qty}")
    if limits.max_order_value is not None and value > limits.max_order_value:
        reject("MAX_VALUE", f"order value {value} is over {limits.max_order_value}")
    if limits.max_adv_fraction is not None:
        if market.adv is None:
            reject(
                "ADV_UNKNOWN", "average daily volume is not known, so the size cannot be checked"
            )
        elif order.qty > limits.max_adv_fraction * market.adv:
            reject(
                "ADV",
                f"{order.qty} shares is over {limits.max_adv_fraction} of the average daily volume {market.adv}",
            )
    if limits.fat_finger_band is not None and order.price is not None:
        if abs(order.price / market.ltp - 1) > limits.fat_finger_band:
            reject(
                "FAT_FINGER",
                f"limit {order.price} is more than {limits.fat_finger_band} from the last price {market.ltp}",
            )
    if order.reduce_only:
        pos = book.position_qty
        reduces = (order.side is Side.SELL and 0 < order.qty <= pos) or (
            order.side is Side.BUY and 0 < order.qty <= -pos
        )
        if not reduces:
            reject(
                "REDUCE_ONLY_VIOLATION",
                f"a {order.side} of {order.qty} does not reduce a position of {pos}",
            )
        return Decision(tuple(out))
    after = abs(book.instrument_value + delta)
    if limits.max_instrument_value is not None and after > limits.max_instrument_value:
        reject("INSTRUMENT_LIMIT", f"position would be {after}, over {limits.max_instrument_value}")
    if limits.max_sector_value is not None:
        if market.sector is None:
            reject(
                "SECTOR_UNKNOWN", "the sector is not known, so the sector limit cannot be checked"
            )
        elif abs(book.sector_value + delta) > limits.max_sector_value:
            reject(
                "SECTOR_LIMIT",
                f"sector exposure would be {abs(book.sector_value + delta)}, over {limits.max_sector_value}",
            )
    gross = book.gross_value - abs(book.instrument_value) + after
    if limits.max_gross_value is not None and gross > limits.max_gross_value:
        reject("GROSS_LIMIT", f"gross exposure would be {gross}, over {limits.max_gross_value}")
    if limits.max_net_value is not None and abs(book.net_value + delta) > limits.max_net_value:
        reject(
            "NET_LIMIT",
            f"net exposure would be {abs(book.net_value + delta)}, over {limits.max_net_value}",
        )
    if limits.check_margin and order.side is Side.BUY and value > book.margin_available:
        reject("MARGIN", f"the order needs {value}, margin available is {book.margin_available}")
    if limits.max_open_orders is not None and book.open_orders >= limits.max_open_orders:
        reject(
            "OPEN_ORDERS",
            f"{book.open_orders} orders are already open (limit {limits.max_open_orders})",
        )
    if limits.max_daily_orders is not None and day.orders >= limits.max_daily_orders:
        reject("DAILY_ORDERS", f"{day.orders} orders today (limit {limits.max_daily_orders})")
    if limits.max_daily_turnover is not None and day.turnover + value > limits.max_daily_turnover:
        reject(
            "DAILY_TURNOVER",
            f"turnover would be {day.turnover + value}, over {limits.max_daily_turnover}",
        )
    if limits.max_daily_loss is not None and day.pnl <= -limits.max_daily_loss:
        reject("DAILY_LOSS", f"today's loss {-day.pnl} has reached {limits.max_daily_loss}")
    if (
        limits.max_consecutive_failures is not None
        and day.consecutive_failures >= limits.max_consecutive_failures
    ):
        reject(
            "CONSEC_FAILURES",
            f"{day.consecutive_failures} execution failures in a row (limit {limits.max_consecutive_failures})",
        )
    return Decision(tuple(out))
