# ruff: noqa: E501
"""Fetch the public market-news RSS feeds, keep the raw feed in the lake, store new headlines with a sentiment reading and the stocks they name (TODO 6.7).
usage: ingest_news.py [--db URL] [--lake DIR]
Safe to repeat (a headline already stored is skipped). A feed that fails (or is refused: a feed with a DOCTYPE/ENTITY declaration is not read) is reported and the others still load."""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.data import news, news_laya
from algo.data.lake import LocalLake
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now, lake, failed, added = datetime.now(UTC), LocalLake(a.lake), [], 0
with psycopg.connect(a.db) as conn:
    migrate(conn)
    stocks = {
        r[0]: (r[0], r[1])
        for r in conn.execute(
            "SELECT symbol, name FROM instrument WHERE asset_class='equity' AND delisted_on IS NULL"
        )
    }
    names, symbols = news.name_index(stocks), list(stocks)
    for source, url in news.FEEDS.items():
        try:
            raw = news.fetch(url)
            lake.put("news", source, now.date(), raw, url=url, fetched_at=now)
            n = news.store(conn, news.parse_rss(raw, source), names, symbols, now)
            conn.commit()
            added += n
            print(f"  {source}: {n} new")
        except Exception as e:  # noqa: BLE001  (one bad feed must not stop the others)
            conn.rollback()
            failed.append(source)
            print(f"  {source}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
    try:  # the second reading: a local model. Failing to run it never fails the job: the keyword reading stands and the next run tries again.
        scored = news_laya.score_pending(conn, news_laya.node_runner(Path("tools/laya")), now)
        conn.commit()
        print(f"  laya: {scored} headline(s) scored")
    except news_laya.LayaError as e:
        conn.rollback()
        print(f"  laya: not scored ({e})", file=sys.stderr)
print(f"news: {added} new headlines, {len(failed)} feed(s) failed")
sys.exit(1 if len(failed) == len(news.FEEDS) else 0)
