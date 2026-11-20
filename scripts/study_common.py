# ruff: noqa: E501
"""Shared inputs for the research studies, so every study prices and costs trades the same way.

BARS   a SQL source (use it where a study used `bar_1d`): Kite daily bars (vendor-adjusted for splits/bonuses, the repo's price series),
       with `delivery_qty` taken from the NSE bhavcopy for the same day and rescaled to the Kite (adjusted) volume, so delivery % = delivery_qty / volume still holds.
       Equity only (instruments that have NSE EQ bars). Data guard: an instrument's history BEFORE its last unexplained one-day jump (close/previous close > 4 or < 0.25) is dropped; Kite's adjustment of some schemes of arrangement is wrong (PRIVISCL shows Rs 0.15 where NSE shows Rs 620 before 2020-08-21). Columns as in bar_1d: instrument_id, ts, open, high, low, close, volume, series, delivery_qty, source, dataset_version.
Costs  round-trip cost of one delivery trade from the cost_schedule TABLE (effective-dated statutory + broker charges, per day) plus slippage (the studies' default:
       5 bps base + 5 bps per 1% of the bar's volume), exactly the policy `algo.paper.jobs.cost_policy` uses. Order size: STUDY_ORDER_VALUE rupees (default 20,000)."""

import os
from datetime import date
from decimal import Decimal

import numpy as np
import psycopg

from algo.backtest.costs import schedule_store
from algo.backtest.costs.calculator import compute_charges
from algo.backtest.costs.slippage import SlippageModel, slippage_bps

BARS = (
    "(SELECT k.instrument_id, k.ts, k.open, k.high, k.low, k.close, k.volume, 'EQ'::text AS series,"
    " n.delivery_qty * k.volume / NULLIF(n.volume, 0) AS delivery_qty, 'kite'::text AS source, k.dataset_version"
    " FROM bar_1d k LEFT JOIN bar_1d n ON n.instrument_id = k.instrument_id AND n.ts = k.ts AND n.source = 'nse' AND n.series = 'EQ'"
    " LEFT JOIN (SELECT instrument_id, max(ts) AS jts FROM (SELECT instrument_id, ts, close / NULLIF(lag(close) OVER (PARTITION BY instrument_id ORDER BY ts), 0) AS r FROM bar_1d WHERE source = 'kite') t"
    " WHERE r > 4 OR r < 0.25 GROUP BY instrument_id) lj ON lj.instrument_id = k.instrument_id"
    " WHERE k.source = 'kite' AND (lj.jts IS NULL OR k.ts >= lj.jts)"
    " AND k.instrument_id IN (SELECT DISTINCT instrument_id FROM bar_1d WHERE source = 'nse' AND series = 'EQ')) bars_kite"
)

ORDER_VALUE = Decimal(os.environ.get("STUDY_ORDER_VALUE", "20000"))
ALLOWED = ("verified", "extracted_unverified", "assumed_backfill")
SLIP = SlippageModel(
    base_bps=Decimal(5), participation_bps_per_pct=Decimal(5), volatility_fraction=Decimal(0)
)


class Costs:
    """Round-trip cost, as a fraction of the order value, of buying on one day and selling on another."""

    def __init__(self, conn: psycopg.Connection, product: str = "DELIVERY") -> None:
        self.book = schedule_store.load_book(conn, "zerodha", ALLOWED)
        self.product = product
        self._cache: dict[tuple[date, str], float] = {}

    def charges(self, day: date, side: str) -> float:
        """Statutory + broker charges of one order of ORDER_VALUE on `day`, as a fraction of its value."""
        key = (day, side)
        if key not in self._cache:
            sch = self.book.for_date(day, self.product)
            p, q = Decimal(100), (ORDER_VALUE / 100).to_integral_value()
            self._cache[key] = float(compute_charges(sch, side, q, p).total / (q * p))
        return self._cache[key]

    def slip(self, turnover: float) -> float:
        """One side's slippage as a fraction: base + participation, where participation = order / the bar's traded value (rupees)."""
        part = Decimal(str(float(ORDER_VALUE) / max(float(turnover), 1.0)))
        return (
            float(slippage_bps(SLIP, participation=part, range_bps=Decimal(0), adv_value=None))
            / 1e4
        )

    def round_trip(
        self, entry_day: date, exit_day: date, entry_turnover: float, exit_turnover: float
    ) -> float:
        return (
            self.charges(entry_day, "BUY")
            + self.charges(exit_day, "SELL")
            + self.slip(entry_turnover)
            + self.slip(exit_turnover)
        )


def describe(costs: Costs) -> str:
    """One line for a study's header: what the cost model charges on a typical liquid trade, today and in 2021."""
    t = 5e7  # a Rs 5 crore bar
    return f"costs from DB cost_schedule (zerodha DELIVERY) + slippage; order Rs {float(ORDER_VALUE):,.0f}; round trip on a Rs 5cr-turnover stock: 2021 {100 * costs.round_trip(date(2021, 6, 1), date(2021, 6, 8), t, t):.3f}%, 2026 {100 * costs.round_trip(date(2026, 6, 1), date(2026, 6, 8), t, t):.3f}%"


def vec_round_trip(
    costs: Costs,
    entry_days: np.ndarray,
    exit_days: np.ndarray,
    entry_turnover: np.ndarray,
    exit_turnover: np.ndarray,
) -> np.ndarray:
    """Vector form of Costs.round_trip (days as datetime64 arrays)."""
    cb = {
        d: costs.charges(d, "BUY")
        for d in {x.astype("datetime64[D]").item() for x in np.unique(entry_days)}
    }
    cs = {
        d: costs.charges(d, "SELL")
        for d in {x.astype("datetime64[D]").item() for x in np.unique(exit_days)}
    }
    b = np.array([cb[x.astype("datetime64[D]").item()] for x in entry_days])
    s = np.array([cs[x.astype("datetime64[D]").item()] for x in exit_days])
    sl = lambda t: np.minimum(5 + 500 * float(ORDER_VALUE) / np.maximum(t, 1.0), 1000) / 1e4  # noqa: E731  same formula as SlippageModel above
    return b + s + sl(entry_turnover) + sl(exit_turnover)


def book_from_db(url: str | None = None):  # type: ignore[no-untyped-def]
    """The zerodha cost schedules from the cost_schedule table (the same book `algo.paper.jobs.cost_policy` uses)."""
    with psycopg.connect(url or os.environ["ALGO_DB_URL"]) as conn:
        return schedule_store.load_book(conn, "zerodha", ALLOWED)


def flat_cost(url: str | None = None, turnover: float = 5e7) -> float:
    """One round-trip cost fraction for a study that charges one number per trade: a 1-week delivery trade on a Rs 5cr-turnover stock, from the DB schedules."""
    with psycopg.connect(url or os.environ["ALGO_DB_URL"]) as conn:
        return Costs(conn).round_trip(date(2025, 6, 2), date(2025, 6, 9), turnover, turnover)


def use_kite_panel(ro) -> None:  # type: ignore[no-untyped-def]
    """Make the rise_odds study helpers read Kite adjusted bars (they read NSE raw bars plus a split mask). Study-only: the product module is untouched."""
    import pandas as pd

    def load_panel(conn: psycopg.Connection, first: date, last: date):  # type: ignore[no-untyped-def]
        rows = conn.execute(
            "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, high::float8, low::float8, close::float8, volume::float8, delivery_qty::float8"
            f" FROM {BARS} WHERE source='kite' AND ts >= %s::date AND ts < %s::date + 1 ORDER BY instrument_id, ts, dataset_version DESC",
            (first, last),
        ).fetchall()
        df = pd.DataFrame(rows, columns=["iid", "d", "h", "l", "c", "v", "dq"])

        def mat(col: str):  # type: ignore[no-untyped-def]
            return df.pivot(index="d", columns="iid", values=col).sort_index().astype("float32")

        return ro.Panel(mat("h"), mat("l"), mat("c"), mat("v"), mat("dq"))

    ro.load_panel = load_panel
    ro.load_splits = lambda conn: []  # Kite prices are already adjusted: nothing to mask
