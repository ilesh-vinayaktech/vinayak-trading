# ruff: noqa: E501
"""Market and sector forecasts (TODO 6.5): probability of UP after 1 and 5 trading days, logged in prediction_log and scored once the outcome is known.
usage: build_predictions.py [--db URL] [--backfill]
Without a flag: tonight's live predictions for the latest day and the resolution of earlier ones (the nightly step, after the market zone). `--backfill`
writes the walk-forward history (each day predicted by a model that had only seen outcomes known by then), a few minutes. Safe to repeat."""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.data.store.migrate import migrate
from algo.market import forecast

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--backfill", action="store_true", help="rebuild the walk-forward history of both products"
)
ap.add_argument(
    "--product",
    choices=forecast.PRODUCTS,
    default="night",
    help="which forecast to make now: night (after the close) or morning (with the US close)",
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db) as conn:
    migrate(conn)
    n = forecast.backfill(conn) if a.backfill else 0
    n += forecast.tonight(conn, a.product, datetime.now(UTC))
    conn.commit()
    print(f"forecast: {n} predictions written or resolved")
    for product, h, live in (
        (q, h, lv)
        for q in (*forecast.PRODUCTS, *forecast.CANDIDATES)
        for h in forecast.HORIZONS
        for lv in (False, True)
    ):
        s = forecast.track_record(conn, forecast.MARKET, h, live, product=product)
        if s:
            print(
                f"  {product} market {h}d {'live' if live else 'walk-forward'}: n={s.n} hit {s.hit_rate:.1%} (always-{'up' if s.base_rate >= 0.5 else 'down'}: {s.base_hit:.1%}) Brier skill {s.brier_skill:+.3f}"
            )
