# ruff: noqa: E501
"""Write today's Kite session for the data loaders from the portal's system data feed (no manual login).

Run after connecting on the portal's Kite page with "Use my connection as the data feed" on.
Writes data/secrets/kite_token.json, the file the loaders already read. Needs ALGO_DB_URL and ALGO_VAULT_KEYS.
Refuses when the feed's API key differs from ZERODHA_API_KEY in the loaders' env file (the loaders sign requests with that one).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.data.providers.kite_session import load_env, save_token
from algo.portal.crypto import KeyRing
from algo.portal.kite_vault import system_feed, system_feed_credentials

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--env", type=Path, default=Path(".env"))
ap.add_argument("--token-file", type=Path, default=Path("data/secrets/kite_token.json"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
with psycopg.connect(a.db) as conn:
    creds = system_feed_credentials(conn, KeyRing.from_env(os.environ), now=now)
    feed = system_feed(conn, now=now)
if creds is None or feed is None:
    sys.exit("no connected system feed: connect on the portal's Kite page and enable the data feed")
key, token = creds
if load_env(a.env).get("ZERODHA_API_KEY") != key:
    sys.exit(
        f"the feed's API key (ending {feed['api_key_hint']}) differs from ZERODHA_API_KEY in {a.env}"
    )
save_token(a.token_file, token, str(feed["owner"]), now)
print(f"wrote {a.token_file} from the feed of {feed['owner']} (key ending {feed['api_key_hint']})")
