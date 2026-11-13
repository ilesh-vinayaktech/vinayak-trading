"""A backtest explained for a person: which stocks were bought and sold, what each trade made
after charges, and where the money ended up. Pure: takes the stored fills and equity curve and
returns strings ready to show.

Buys are matched to sells first-in-first-out per stock; buy and sell charges are split by quantity.
Splits and bonuses (the extra shares the engine's ledger added on the ex-date) rescale the open lots
first, keeping their cost, so a sale of the extra shares pairs instead of vanishing.
Closed-trade P&L (round_trips, summary) is realised only; the headline uses the equity curve, which
also holds open positions at market and dividends, so the two can differ by design."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from algo.backtest.validation.stats import annualised_sharpe, max_drawdown

# seq, day, instrument_id, side, qty, price, charges
Fill = tuple[int, date, int, str, Decimal, Decimal, Decimal]
# ex-date, instrument_id, extra shares the engine's ledger added (backtest_ledger kind SPLIT)
Split = tuple[date, int, Decimal]
_Q4 = Decimal("0.0001")
_ZERO = Decimal(0)
_QTY = Decimal("0.00000001")


@dataclass(frozen=True)
class Trip:
    instrument_id: int
    qty: Decimal
    entry_day: date
    entry_price: Decimal
    exit_day: date
    exit_price: Decimal
    charges: Decimal

    @property
    def gross(self) -> Decimal:
        return (self.exit_price - self.entry_price) * self.qty

    @property
    def net(self) -> Decimal:
        return self.gross - self.charges

    @property
    def days(self) -> int:
        return (self.exit_day - self.entry_day).days


def _s(v: Decimal) -> str:
    q = v.quantize(_Q4)
    return format(q.normalize(), "f") if q else "0"


def _ratio(a: Decimal, b: Decimal) -> str | None:
    return None if not b else format((a / b).quantize(_Q4), "f")


def _rescale(lots: deque[list[Any]], extra: Decimal) -> None:
    """A split or bonus: each lot holds more shares, each at a proportionally lower cost."""
    held = sum((lot[0] for lot in lots), _ZERO)
    if held <= 0:
        return
    f = (held + extra) / held
    for lot in lots:
        lot[0] = (lot[0] * f).quantize(_QTY)
        lot[1] = lot[1] * f
        lot[2] = lot[2] / f


def _pair(
    fills: Sequence[Fill], names: Mapping[int, str], splits: Sequence[Split] = ()
) -> tuple[list[Trip], list[dict[str, Any]]]:
    # instrument -> lots of [qty left, original qty, price, day, buy charges]
    lots: dict[int, deque[list[Any]]] = {}
    trips: list[Trip] = []
    pending = deque(sorted(splits, key=lambda x: x[0]))
    for _seq, day, iid, side, qty, price, charges in sorted(fills, key=lambda f: f[0]):
        while pending and pending[0][0] <= day:  # the ex-date comes before that day's trades
            _d, sid, extra = pending.popleft()
            if sid in lots:
                _rescale(lots[sid], extra)
        if side == "BUY":
            lots.setdefault(iid, deque()).append([qty, qty, price, day, charges])
            continue
        left = qty
        q = lots.get(iid)
        # ponytail: a sell with nothing held (conversions not modelled as fills) is skipped
        while left > 0 and q:
            lot = q[0]
            take = min(left, lot[0])
            fee = lot[4] * take / lot[1] + charges * take / qty
            trips.append(Trip(iid, take, lot[3], lot[2], day, price, fee))
            lot[0] -= take
            left -= take
            if lot[0] == 0:
                q.popleft()
    for _d, sid, extra in pending:  # after the last trade: the shares still held
        if sid in lots:
            _rescale(lots[sid], extra)
    open_ = []
    for i, q in lots.items():
        qty = sum((lot[0] for lot in q), _ZERO)
        if qty:
            open_.append(
                {
                    "symbol": names.get(i, str(i)),
                    "instrument_id": i,
                    "qty": _s(qty),
                    "lots": len(q),
                    "entry_day": str(min(lot[3] for lot in q)),  # first bought
                    "entry_price": _s(sum((lot[0] * lot[2] for lot in q), _ZERO) / qty),  # average
                }
            )
    return trips, sorted(open_, key=lambda o: (o["entry_day"], o["symbol"]))


def round_trips(fills: Sequence[Fill], splits: Sequence[Split] = ()) -> list[Trip]:
    """Buys paired with sells, first in first out per stock (the closed trades only)."""
    return _pair(fills, {}, splits)[0]


def _stats(trips: Sequence[Trip]) -> dict[str, Any]:
    wins = [t.net for t in trips if t.net > 0]
    losses = [t.net for t in trips if t.net <= 0]
    gp, gl = sum(wins, _ZERO), -sum(losses, _ZERO)
    charges = sum((t.charges for t in trips), _ZERO)
    n = len(trips)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _ratio(Decimal(len(wins)), Decimal(n)),
        "net_pnl": _s(gp - gl),
        "gross_profit": _s(gp),
        "gross_loss": _s(gl),
        "profit_factor": _ratio(gp, gl),  # undefined without a losing trade
        "avg_win": _s(gp / len(wins)) if wins else None,
        "avg_loss": _s(sum(losses, _ZERO) / len(losses)) if losses else None,
        "charges": _s(charges),
        "pre_charge_pnl": _s(gp - gl + charges),
        "cost_drag": _ratio(charges, gp - gl + charges) if gp - gl + charges > 0 else None,
        "avg_holding_days": _ratio(Decimal(sum(t.days for t in trips)), Decimal(n)),
    }


_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _monthly(trips: Sequence[Trip]) -> list[dict[str, Any]]:
    months: dict[str, list[Trip]] = {}
    for t in trips:
        months.setdefault(t.exit_day.strftime("%Y-%m"), []).append(t)
    return [
        {"month": m, "net": _s(sum((t.net for t in ts), _ZERO)), "trades": len(ts)}
        for m, ts in sorted(months.items())
    ]


def _weekdays(trips: Sequence[Trip]) -> list[dict[str, Any]]:
    out = []
    for i, name in enumerate(_DAYS[:5]):
        ts = [t for t in trips if t.exit_day.weekday() == i]
        wins = sum(1 for t in ts if t.net > 0)
        out.append(
            {
                "weekday": name,
                "trades": len(ts),
                "net": _s(sum((t.net for t in ts), _ZERO)),
                "win_rate": _ratio(Decimal(wins), Decimal(len(ts))),
            }
        )
    return out


def _distribution(trips: Sequence[Trip]) -> list[dict[str, Any]]:
    """Trades by return, in 2% steps from -10% to +10% with a bucket for each tail."""
    counts = dict.fromkeys(range(-6, 6), 0)
    for t in trips:
        r = t.net / (t.entry_price * t.qty)
        counts[max(-6, min(5, math.floor(r / Decimal("0.02"))))] += 1
    label = {-6: "below -10%", 5: "10% and above"}
    return [
        {"label": label.get(i, f"{2 * i}% to {2 * i + 2}%"), "count": n} for i, n in counts.items()
    ]


def _curve(equity: Sequence[tuple[date, Decimal]]) -> tuple[list[dict[str, str]], Decimal]:
    peak, worst, out = _ZERO, _ZERO, []
    for d, v in equity:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak else _ZERO
        worst = min(worst, dd)
        out.append({"date": str(d), "equity": _s(v), "drawdown": format(dd.quantize(_Q4), "f")})
    return out, worst


def no_comparison(name: str, note: str | None) -> dict[str, Any]:
    """The comparison block with nothing in it, and the reason."""
    return {
        "name": name, "note": note, "curve": [], "return": None, "final": None,
        "max_drawdown": None, "sharpe": None, "strategy_return": None,
        "strategy_max_drawdown": None, "strategy_sharpe": None,
    }  # fmt: skip


def _compare(
    equity: Sequence[tuple[date, Decimal]], name: str, levels: Mapping[date, Decimal]
) -> dict[str, Any]:
    """The index over the run's own days, rebased to the amount the run started with."""
    days = [d for d, _ in equity]
    missing = [d for d in days if d not in levels]
    out = no_comparison(name, None)
    if missing or len(equity) < 2:
        out["note"] = (
            f"{name} has no value for {len(missing)} of {len(days)} days of this run"
            if missing
            else "the run is too short to compare"
        )
        return out
    start = equity[0][1]
    rebased = [start * levels[d] / levels[days[0]] for d in days]
    idx_ret = [float(b / a - 1) for a, b in zip(rebased, rebased[1:], strict=False)]
    run_ret = [float(b / a - 1) for (_, a), (_, b) in zip(equity, equity[1:], strict=False)]

    def two(x: float | None) -> str | None:
        return None if x is None else format(x, ".2f")

    out.update(
        curve=[{"date": str(d), "level": _s(v)} for d, v in zip(days, rebased, strict=True)],
        final=_s(rebased[-1]),
        **{"return": _ratio(rebased[-1] - start, start)},
        max_drawdown=format(max_drawdown(idx_ret), ".4f"),
        sharpe=two(annualised_sharpe(idx_ret)),
        strategy_return=_ratio(equity[-1][1] - start, start),
        strategy_max_drawdown=format(max_drawdown(run_ret), ".4f"),
        strategy_sharpe=two(annualised_sharpe(run_ret)),
    )
    return out


def build_report(
    fills: Sequence[Fill],
    equity: Sequence[tuple[date, Decimal]],
    initial_cash: Decimal,
    names: Mapping[int, str],
    benchmark: tuple[str, Mapping[date, Decimal]] | None = None,
    splits: Sequence[Split] = (),
    total_charges: Decimal | None = None,
    dividends: Decimal = _ZERO,
) -> dict[str, Any]:
    """total_charges: everything the run paid (the run's own fee total, which also holds charges
    that belong to no trade); default: the charges of every fill, open buys included."""
    trips, open_ = _pair(fills, names, splits)
    curve, worst = _curve(equity)
    final = equity[-1][1] if equity else None

    def sym(i: int) -> str:
        return names.get(i, str(i))

    by_stock = []
    for iid in sorted({t.instrument_id for t in trips}, key=sym):
        s = _stats([t for t in trips if t.instrument_id == iid])
        by_stock.append(
            {
                "symbol": sym(iid),
                "trades": s["trades"],
                "net": s["net_pnl"],
                "win_rate": s["win_rate"],
                "charges": s["charges"],
            }
        )
    return {
        "headline": {
            "initial": _s(initial_cash),
            "final": None if final is None else _s(final),
            "change": None if final is None else _s(final - initial_cash),
            "return": None if final is None else _ratio(final - initial_cash, initial_cash),
            "max_drawdown": format(worst.quantize(_Q4), "f"),
            "charges": _s(
                sum((f[6] for f in fills), _ZERO) if total_charges is None else total_charges
            ),
            "dividends": _s(dividends),
        },
        "summary": _stats(trips),
        "curve": curve,
        "round_trips": [
            {
                "instrument_id": t.instrument_id,
                "symbol": sym(t.instrument_id),
                "qty": _s(t.qty),
                "entry_day": str(t.entry_day),
                "entry_price": _s(t.entry_price),
                "exit_day": str(t.exit_day),
                "exit_price": _s(t.exit_price),
                "gross": _s(t.gross),
                "charges": _s(t.charges),
                "net": _s(t.net),
                "holding_days": t.days,
                "return": _ratio(t.net, t.entry_price * t.qty),
            }
            for t in trips
        ],
        "monthly": _monthly(trips),
        "by_weekday": _weekdays(trips),
        "distribution": _distribution(trips),
        "benchmark": None if benchmark is None else _compare(equity, *benchmark),
        "open_positions": open_,
        "by_stock": by_stock,
    }
