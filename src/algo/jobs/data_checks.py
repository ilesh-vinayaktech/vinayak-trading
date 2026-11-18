# ruff: noqa: E501
"""Is the live and news data actually arriving? (the portal's Data Health page and the `live-data-check` job)

The price-bar freshness check and the job-ran-recently check already exist; they cannot see the feeds added since: the live index quotes and minute bars, the news feed, the Laya scoring of
headlines, the baseline the live market zone starts from, and the index constituent lists. Each rule here says what is wrong in one sentence, or nothing. A rule that depends on the market being
open only applies while the equity feed itself is live (so a holiday or a stopped feed is the feed check's business, not a stack of derived alarms)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import psycopg

from algo.live.bar_store import read_status
from algo.live.index_store import TRACKED
from algo.live.market_calendar import IST
from algo.market import live_zone

INDEX_QUOTE_MAX_AGE = timedelta(minutes=2)
INDEX_BAR_MAX_AGE = timedelta(
    minutes=4
)  # a minute bar is stored a few seconds after its minute ends
MIN_INDEX_SHARE = (
    0.8  # of the followed indices, this share must have a quote while the feed is live
)
NEWS_MAX_AGE = timedelta(
    hours=8
)  # the newest headline's publication time: the feeds publish all day
LAYA_WAIT = timedelta(
    minutes=30
)  # a headline may wait this long for the model before it is a problem
LISTS_MAX_AGE_DAYS = 14  # the constituent lists are captured weekly
BASELINE_FROM = time(8, 30)  # on a trading day, the live zone's baseline should exist from here


@dataclass(frozen=True)
class Problem:
    level: str  # attention | down
    text: str


def _age(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return (
        f"{minutes} min"
        if minutes < 120
        else f"{minutes // 60} h"
        if minutes < 48 * 60
        else f"{minutes // 1440} d"
    )


def _feed_is_live(conn: psycopg.Connection, now: datetime) -> bool:
    feed = read_status(conn)
    last = feed["last_tick_at"] if feed else None
    return bool(
        feed
        and feed["state"] == "CONNECTED"
        and last is not None
        and now - last <= timedelta(seconds=60)
    )


def problems(
    conn: psycopg.Connection, now: datetime, lake: Path = Path("data/lake")
) -> list[Problem]:
    out: list[Problem] = []
    if _feed_is_live(conn, now):
        newest = conn.execute(
            "SELECT max(updated_at), count(*) FILTER (WHERE updated_at >= %s) FROM index_live_quote",
            (now - INDEX_QUOTE_MAX_AGE,),
        ).fetchone()
        assert newest is not None
        quoted = newest[1]
        if newest[0] is None or quoted < MIN_INDEX_SHARE * len(TRACKED):
            out.append(
                Problem(
                    "attention",
                    f"Only {quoted} of {len(TRACKED)} indices have a live quote while the market feed is running: the index cards, sector prices and the live market zone are going stale (restart the feed so it picks the indices up).",
                )
            )
        bar = conn.execute("SELECT max(ts) FROM index_bar_1m").fetchone()
        if bar and bar[0] is not None and now - bar[0] > INDEX_BAR_MAX_AGE and quoted > 0:
            out.append(
                Problem(
                    "attention",
                    f"The newest index minute bar is {_age(now - bar[0])} old while the feed is running: index minutes are not being stored.",
                )
            )
    story = conn.execute("SELECT max(published_at) FROM news_item").fetchone()
    if story and story[0] is not None and now - story[0] > NEWS_MAX_AGE:
        out.append(
            Problem(
                "attention",
                f"No new headline for {_age(now - story[0])}: the news job may have stopped, or every feed is failing.",
            )
        )
    waiting = conn.execute(
        "SELECT count(*) FROM news_item WHERE laya_sentiment IS NULL AND published_at >= %s AND first_seen_at < %s",
        (now - timedelta(hours=24), now - LAYA_WAIT),
    ).fetchone()
    if waiting and waiting[0] > 0:
        n = waiting[0]
        out.append(
            Problem(
                "attention",
                f"{n} headline{'s have' if n != 1 else ' has'} waited over {int(LAYA_WAIT.total_seconds() // 60)} min for the Laya model and still show the keyword reading: is the model installed (tools/laya)?",
            )
        )
    local = now.astimezone(IST)
    today = local.date()
    if local.weekday() < 5 and local.time() >= BASELINE_FROM:
        last = live_zone.last_bar(conn, today)
        have = conn.execute("SELECT max(last_bar) FROM breadth_baseline").fetchone()
        if last is not None and (have is None or have[0] is None or have[0] < last):
            out.append(
                Problem(
                    "attention",
                    f"The live market zone has no baseline for the last trading day ({last}): it will show the nightly snapshot until the market-zone job (or refresh_baseline) runs.",
                )
            )
    newest_list = _newest_list_day(lake)
    if newest_list is not None and (today - newest_list).days > LISTS_MAX_AGE_DAYS:
        out.append(
            Problem(
                "attention",
                f"The index constituent lists are {(today - newest_list).days} days old (captured weekly by constituents-weekly): the stocks shown inside an index may be out of date.",
            )
        )
    return out


def _newest_list_day(lake: Path) -> date | None:
    days = sorted((lake / "raw/niftyindices/nifty50_list").glob("dt=*"))
    return date.fromisoformat(days[-1].name[3:]) if days else None
