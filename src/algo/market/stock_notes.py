# ruff: noqa: E501
"""The notes for a batch of stocks (TODO 6.8 follow-up): the chart facts from `notes.price_notes`, plus what the other tables know: headlines naming the stock in the last
three days, announced corporate actions in the next fortnight, bulk and block deals this week and insider trades in the last fortnight. Reads the database only."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Any

import psycopg

from algo.data.corporate_actions import upcoming_within
from algo.live.market_calendar import IST
from algo.market import notes as chart
from algo.market.notes import RANK_CONTEXT, LiveDay, Note

NEWS_DAYS, ACTION_DAYS, DEAL_DAYS, INSIDER_DAYS = 3, 14, 5, 14
NEWS_TONE = 0.2  # an average headline reading beyond this either way is called positive or negative
MAX_IDS = 60


def load_bars(conn: psycopg.Connection, iid: int) -> dict[str, list[Any]]:
    """The stock's daily bars (oldest first, at most 400) since its latest split or bonus, as parallel lists: day, high, low, close, volume and delivery %."""
    split = conn.execute(
        "SELECT max(ex_date) FROM corporate_action WHERE instrument_id=%s AND kind IN ('split','bonus') AND status='ok' AND ex_date <= current_date", (iid,)
    ).fetchone()  # fmt: skip
    cut = split[0] if split else None
    rows = conn.execute(
        "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date, high::float8, low::float8, close::float8, volume::float8, CASE WHEN series='EQ' THEN delivery_qty::float8 END FROM ("
        " SELECT DISTINCT ON (ts) * FROM bar_1d WHERE instrument_id=%s AND source='nse' ORDER BY ts, dataset_version DESC) x"
        " WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date >= coalesce(%s::date, '1900-01-01') ORDER BY ts DESC LIMIT 400", (iid, cut)
    ).fetchall()[::-1]  # fmt: skip
    return {
        "day": [r[0] for r in rows], "high": [r[1] for r in rows], "low": [r[2] for r in rows], "close": [r[3] for r in rows], "volume": [r[4] for r in rows],
        "delivery_pct": [100 * r[5] / r[4] if r[5] is not None and r[4] > 0 else None for r in rows],
    }  # fmt: skip


def notes_for(conn: psycopg.Connection, ids: list[int], now: datetime) -> dict[int, list[Note]]:
    """Notes, most important first, for each of up to MAX_IDS stocks; a stock with nothing to say is absent."""
    ids = sorted(set(ids))[:MAX_IDS]
    today = now.astimezone(IST).date()
    start = datetime.combine(today, time(0), IST)
    symbol = {
        i: s
        for i, s in conn.execute(
            "SELECT instrument_id, symbol FROM instrument WHERE instrument_id = ANY(%s)", (ids,)
        )
    }
    live = {
        i: LiveDay(None if o is None else float(o), float(h if h is not None else ltp), float(lo if lo is not None else ltp), float(ltp), float(vol or 0))
        for i, ltp, o, h, lo, vol in conn.execute(
            "SELECT instrument_id, ltp, day_open, day_high, day_low, volume FROM live_quote WHERE instrument_id = ANY(%s) AND updated_at >= %s AND ltp > 0", (ids, start)
        )
    }  # fmt: skip
    out: dict[int, list[Note]] = defaultdict(list)
    for iid in ids:
        b = load_bars(conn, iid)
        if (
            iid in live and b["day"] and b["day"][-1] >= today
        ):  # today's stored bar (if any) is replaced by the live day, never counted twice
            for k in b:
                b[k] = b[k][:-1]
        out[iid].extend(
            chart.price_notes(
                b["high"], b["low"], b["close"], b["volume"], b["delivery_pct"], live.get(iid)
            )
        )
    names = {s: i for i, s in symbol.items()}
    for sym, n, avg, title in conn.execute(
        "SELECT s, count(*), avg(sentiment), (array_agg(title ORDER BY published_at DESC))[1] FROM news_item, unnest(symbols) s"
        " WHERE s = ANY(%s) AND published_at >= %s GROUP BY s", (list(names), now - timedelta(days=NEWS_DAYS))
    ):  # fmt: skip
        tone = "info" if avg is None or abs(avg) < NEWS_TONE else ("good" if avg > 0 else "bad")
        mood = (
            ""
            if avg is None or tone == "info"
            else (", mostly positive" if avg > 0 else ", mostly negative")
        )
        out[names[sym]].append(
            Note(
                "news",
                tone,
                f"{n} headline{'s' if n != 1 else ''}{mood}",
                RANK_CONTEXT,
                f"Latest: {title}",
            )
        )
    for iid, items in upcoming_within(conn, ids, today, ACTION_DAYS).items():
        for a in items[:2]:
            kind = str(a["kind"]).replace("_", " ")
            days = (a["ex_date"] - today).days
            amount = f" of {a['amount']:,.2f}" if a["amount"] is not None else ""
            out[iid].append(
                Note(
                    "action",
                    "warn",
                    f"Ex-{kind} {'today' if days == 0 else f'in {days}d'}",
                    RANK_CONTEXT,
                    f"{kind.capitalize()}{amount}, ex-date {a['ex_date']}. The price is adjusted on the ex-date.",
                )
            )
    for sym, kind, side, qty, price, on, client in conn.execute(
        "SELECT symbol, kind, side, quantity, price, trade_date, client FROM nse_bulk_block_deal WHERE symbol = ANY(%s) AND trade_date >= %s ORDER BY trade_date DESC, quantity DESC",
        (list(names), today - timedelta(days=DEAL_DAYS)),
    ):
        buy = str(side).upper().startswith("B")
        out[names[sym]].append(
            Note(
                "deal",
                "good" if buy else "bad",
                f"{kind.capitalize()} deal: {'bought' if buy else 'sold'}",
                RANK_CONTEXT,
                f"{client} {'bought' if buy else 'sold'} {int(qty):,} shares at {float(price):,.2f} on {on}",
            )
        )
    for sym, buys, sells, n in conn.execute(
        "SELECT symbol, coalesce(sum(value) FILTER (WHERE transaction_type ILIKE 'buy%%' OR transaction_type ILIKE 'acq%%'), 0),"
        " coalesce(sum(value) FILTER (WHERE transaction_type ILIKE 'sell%%' OR transaction_type ILIKE 'disp%%'), 0), count(*)"
        " FROM nse_insider_trade WHERE symbol = ANY(%s) AND broadcast_at >= %s GROUP BY symbol", (list(names), now - timedelta(days=INSIDER_DAYS))
    ):  # fmt: skip
        if buys == sells:
            continue
        net, bought = abs(float(buys - sells)), buys > sells
        out[names[sym]].append(
            Note(
                "insider",
                "good" if bought else "bad",
                f"Insiders {'buying' if bought else 'selling'} ₹{net / 1e7:,.1f} cr",
                RANK_CONTEXT,
                f"{n} insider filing{'s' if n != 1 else ''} in {INSIDER_DAYS} days; net {'bought' if bought else 'sold'} ₹{net / 1e7:,.2f} crore",
            )
        )
    return {i: sorted(v, key=lambda x: x.rank) for i, v in out.items() if v}
