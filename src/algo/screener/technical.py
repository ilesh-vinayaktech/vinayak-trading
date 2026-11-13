# ruff: noqa: E501
"""Technical fields of one stock from its daily bars (oldest first). Pure; Decimal; None where the history is too short."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from decimal import Decimal

from algo.indicators.catalog import Bars, compute
from algo.indicators.core import sma_last

D = Decimal
HUNDRED = D(100)
CHANGES = {"chg_1d": 1, "chg_1w": 5, "chg_1m": 21, "chg_3m": 63, "chg_6m": 126, "chg_1y": 252}
YEAR = 252


def _pct(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None or b == 0 else (a / b - 1) * HUNDRED


def _last(series: Sequence[Decimal | None]) -> Decimal | None:
    return series[-1] if series else None


def technicals(bars: Bars, fields: Collection[str] | None = None) -> dict[str, Decimal | None]:
    close, n = list(bars.close), len(bars)
    out: dict[str, Decimal | None] = {"price": close[-1] if n else None}
    for key, back in CHANGES.items():
        out[key] = _pct(close[-1], close[-1 - back]) if n > back else None
    sma50, sma200 = sma_last(close, 50), sma_last(close, 200)
    out["price_vs_sma50"] = _pct(out["price"], sma50)
    out["price_vs_sma200"] = _pct(out["price"], sma200)
    out["sma50_vs_sma200"] = _pct(sma50, sma200)
    year = close[-YEAR:]
    out["pct_from_52w_high"] = _pct(out["price"], max(year)) if n >= YEAR // 2 else None
    out["pct_from_52w_low"] = _pct(out["price"], min(year)) if n >= YEAR // 2 else None
    vol = list(bars.volume)
    avg_vol = sma_last(vol[:-1], 20) if n > 20 else None
    out["volume_ratio"] = None if not avg_vol else vol[-1] / avg_vol
    traded = [c * v for c, v in zip(close[-20:], vol[-20:], strict=True)]
    out["turnover_cr"] = sum(traded, D(0)) / len(traded) / D(10_000_000) if n >= 20 else None

    # the three indicators are the slow part: with `fields` given, only the ones asked for are worked out (the rest are None)
    def want(k: str) -> bool:
        return fields is None or k in fields

    out["rsi_14"] = (
        _last(compute("rsi:14", bars)[2]["value"]) if n > 14 and want("rsi_14") else None
    )
    out["macd_hist"] = (
        _last(compute("macd", bars)[2]["hist"]) if n > 35 and want("macd_hist") else None
    )
    out["adx_14"] = _last(compute("adx:14", bars)[2]["adx"]) if n > 28 and want("adx_14") else None
    return out
