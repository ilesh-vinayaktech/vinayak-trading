# ruff: noqa: E501
"""Evidence for the regular session hours of every day in the stored 1-minute history: the first and last bar of each day, and the days
that are not 09:15-15:29. Every such day must be a listed special session (config/exchange_sessions.json) or a recorded one-bar
oddity; anything else stops the run. Writes docs/session-evidence/minute_hours_scan.json (deterministic for the same data).
usage: scan_session_hours.py --through YYYY-MM-DD [--db URL]"""

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--through", type=dt.date.fromisoformat, required=True, help="last COMPLETE day to scan"
)
ap.add_argument("--sessions", type=Path, default=Path("config/exchange_sessions.json"))
ap.add_argument("--out", type=Path, default=Path("docs/session-evidence/minute_hours_scan.json"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
listed = {s["date"] for s in json.loads(a.sessions.read_text())["sessions"]}
REGULAR = ("09:15", "15:29")  # first bar open, last bar open
days = regular = 0
first_day = None
unlisted, listed_seen = [], []
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as conn:
    first_ts = conn.execute("SELECT min(ts AT TIME ZONE 'Asia/Kolkata') FROM bar_1m").fetchone()[0]
    y, m = first_ts.year, first_ts.month
    while dt.date(y, m, 1) <= a.through:
        lo, hi = (
            dt.date(y, m, 1),
            min(dt.date(y + (m == 12), m % 12 + 1, 1), a.through + dt.timedelta(days=1)),
        )
        for d, mn, mx, n in conn.execute(
            "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date, min((ts AT TIME ZONE 'Asia/Kolkata')::time), max((ts AT TIME ZONE 'Asia/Kolkata')::time),"
            " count(DISTINCT instrument_id) FROM bar_1m WHERE ts >= (%s::date::timestamp AT TIME ZONE 'Asia/Kolkata')"
            " AND ts < (%s::date::timestamp AT TIME ZONE 'Asia/Kolkata') GROUP BY 1 ORDER BY 1", (lo, hi)):  # fmt: skip
            days += 1
            first_day = first_day or d
            row = {
                "date": str(d),
                "weekday": d.strftime("%a"),
                "first_bar": str(mn)[:5],
                "last_bar": str(mx)[:5],
                "instruments": n,
            }
            if (row["first_bar"], row["last_bar"]) == REGULAR:
                regular += 1
            elif str(d) in listed:
                listed_seen.append(row)
            else:
                unlisted.append(row)
        y, m = (y + (m == 12), m % 12 + 1)
# a day whose last bar opens at 15:30 has one extra closing-price bar: noted, not a different session
oddities = [r for r in unlisted if r["first_bar"] == "09:15" and r["last_bar"] == "15:30"]
real = [r for r in unlisted if r not in oddities]
doc = {
    "what": "first and last 1-minute bar of every day in the stored history (Kite), against the regular session 09:15-15:30 (last bar opens 15:29)",
    "scanned": {"first_day": str(first_day), "last_day": str(a.through), "days": days},
    "regular_days": regular,
    "special_sessions_listed_in_config": listed_seen,
    "one_extra_bar_at_15_30": oddities,
    "unexplained": real,
    "sessions_file_sha256": hashlib.sha256(a.sessions.read_bytes()).hexdigest(),
}
if real:
    sys.exit(
        "days that are neither regular nor a listed session:\n  " + "\n  ".join(map(str, real))
    )
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(doc, indent=1) + "\n")
print(
    f"{days} days: {regular} regular, {len(listed_seen)} listed special sessions, {len(oddities)} with one extra 15:30 bar, 0 unexplained"
)
