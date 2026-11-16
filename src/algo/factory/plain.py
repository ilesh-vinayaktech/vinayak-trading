# ruff: noqa: E501
"""A strategy definition in plain words, for the strategy pages.

Callers: algo.api.intel_routes (definitions) and tests/unit/factory/test_plain.py. Nothing similar exists: algo.factory.signals.explain writes the reasons of one decision with the numbers;
this writes the rule itself with no feature names or operators. User's instruction: "I want Strategy definitions in simple language which is easy to understand"."""

from __future__ import annotations

from decimal import Decimal

from algo.factory.dsl import MARKET_BREADTH, Condition, Group, StrategyDef

PHRASES = {
    "ret_1d": "price change over the last day",
    "ret_5d": "price change over the last week",
    "ret_20d": "price change over the last month",
    "ret_60d": "price change over the last 3 months",
    "ret_120d": "price change over the last 6 months",
    "ret_252d": "price change over the last 12 months",
    "vol_20d": "price swings over the last month (volatility)",
    "vol_60d": "price swings over the last 3 months (volatility)",
    "range_vol_20d": "daily high-to-low range over the last month",
    "max_drawdown_60d": "worst fall from a recent peak over the last 3 months",
    "dist_sma_50d": "how far the price is above its 50-day average",
    "dist_sma_200d": "how far the price is above its 200-day average",
    "dist_high_252d": "how close the price is to its 52-week high",
    "dist_low_252d": "how far the price is above its 52-week low",
    "traded_value_20d": "money traded per day over the last month",
    "volume_ratio_20_60d": "recent trading volume compared with the last 3 months",
    "atr_14d": "average daily price range (14 days)",
    "atr_pct_14d": "average daily price range as a share of the price (14 days)",
    "rsi_14d": "recent strength of buying versus selling (RSI)",
}
WHEN = {"DAILY": "Every trading day", "WEEKLY": "Once a week", "MONTHLY": "Once a month"}
HOW_OFTEN = {"DAILY": "every day", "WEEKLY": "once a week", "MONTHLY": "once a month"}


def phrase(feature: str) -> str:
    return PHRASES.get(feature, feature.replace("_", " "))


def _n(v: Decimal) -> str:
    return format(v.normalize(), "f")


def _market(c: Condition, buying: bool) -> str:
    share = _n(c.value)
    if c.op in (">=", ">"):
        return f"at least {share}% of all stocks are above their 200-day average"
    return f"fewer than {share}% of all stocks are above their 200-day average"


def _one(c: Condition, buying: bool) -> str:
    if c.feature == MARKET_BREADTH:
        return _market(c, buying)
    if c.op in ("TOP_PERCENT", "BOTTOM_PERCENT"):
        side = "highest" if c.op == "TOP_PERCENT" else "lowest"
        return f"{'it is among' if buying else 'it falls into'} the {_n(c.value)}% of stocks with the {side} {phrase(c.feature)}"
    word = {
        ">": "is above",
        ">=": "is at least",
        "<": "is below",
        "<=": "is at most",
        "==": "equals",
        "!=": "is not",
    }[c.op]
    return f"{phrase(c.feature)} {word} {_n(c.value)}"


def _sentence(group: Group, lead: str, buying: bool) -> str:
    conds = group.conditions()
    if len(conds) == 1:
        c = conds[0]
        if c.feature == MARKET_BREADTH and not buying:
            return f"{lead}everything when {_market(c, False)}."
        return f"{lead}{_one(c, buying)}." if buying else f"{lead}it when {_one(c, buying)}."
    joiner = " and " if group.mode() == "all" else " or "
    parts = [_one(c, buying) for c in conds]
    if buying:
        return f"{lead}{joiner.join(parts)}."
    head = "all of these are true" if group.mode() == "all" else "any one of these is true"
    return f"{lead}it when {head}: " + "; ".join(parts) + "."


def describe(d: StrategyDef) -> dict[str, str]:
    """{when, summary, buy, sell, size}: each a plain sentence."""
    buy_group, sell_group = d.entry, d.exit
    buy = _sentence(buy_group, "Buy a stock when ", True)
    sell = _sentence(sell_group, "Sell ", False)
    first = d.entry.conditions()[0]
    sell_first = d.exit.conditions()[0]
    summary = f"{WHEN[d.rebalance]}: "
    one_each = len(d.entry.conditions()) == 1 and len(d.exit.conditions()) == 1
    if (
        one_each
        and first.op in ("TOP_PERCENT", "BOTTOM_PERCENT")
        and sell_first.op in ("TOP_PERCENT", "BOTTOM_PERCENT")
        and first.feature == sell_first.feature
    ):
        side = lambda c: "highest" if c.op == "TOP_PERCENT" else "lowest"  # noqa: E731
        summary += f"buy the {_n(first.value)}% of stocks with the {side(first)} {phrase(first.feature)}; sell when one falls into the {_n(sell_first.value)}% with the {side(sell_first)}."
    else:
        summary += buy[0].lower() + buy[1:]
    cap = _n(d.risk.max_position_percent)
    size = f"Hold at most {d.position.max_positions} stocks, each the same size (never more than {cap}% of the money in one)."
    if d.position.sizing == "INVERSE_VOLATILITY":
        size = f"Hold at most {d.position.max_positions} stocks; calmer stocks get more money (never more than {cap}% in one)."
    return {"when": WHEN[d.rebalance], "summary": summary, "buy": buy, "sell": sell, "size": size}
