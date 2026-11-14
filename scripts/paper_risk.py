# ruff: noqa: E501
"""An account's risk limits (checked when you approve an order).
  paper_risk.py show --email jane@example.com
  paper_risk.py set --email jane@example.com --json '{"max_order_value": 50000, "max_open_orders": 5, "trading_hours": ["09:15", "15:30"]}'
  paper_risk.py clear --email jane@example.com
Keys: allowed, restricted, max_order_qty, max_order_value, max_adv_fraction, fat_finger_band, max_instrument_value, max_sector_value,
max_gross_value, max_net_value, check_margin, max_open_orders, trading_hours, max_daily_orders, max_daily_turnover, max_daily_loss,
max_consecutive_failures. An unknown key is refused. Paper values are at cost; sector and daily-loss limits are not meaningful yet."""

import argparse
import json
import os
import sys

import psycopg

from algo.data.store.migrate import migrate
from algo.paper import risk
from algo.risk.limits import LimitsError

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("cmd", choices=("show", "set", "clear"))
ap.add_argument("--email", required=True)
ap.add_argument("--json")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    row = conn.execute(
        "SELECT user_id FROM portal_user WHERE lower(email)=lower(%s)", (a.email,)
    ).fetchone()
    if row is None:
        sys.exit(f"no user {a.email}")
    if a.cmd == "set":
        try:
            risk.set_limits(conn, row[0], json.loads(a.json or "null"))
        except (LimitsError, ValueError, TypeError) as e:
            sys.exit(f"refused: {e}")
    elif a.cmd == "clear":
        risk.set_limits(conn, row[0], None)
    stored = conn.execute("SELECT risk FROM paper_account WHERE user_id=%s", (row[0],)).fetchone()
    print(json.dumps(None if stored is None else stored[0], indent=1))
