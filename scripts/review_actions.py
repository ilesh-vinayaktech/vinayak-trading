"""Manual review of corporate actions the feed cannot price.
  list     [--kind K ...] [--symbol S ...] [--since D] [--all]   the queue, with price context
  resolve  --symbol S --ex-date D --kind K --method ignore|direct|demerger|rights --note TEXT
           --by WHO [--param name=value ...]
  verify   --symbol S --ex-date D --kind K --by WHO --source-type T --source-url U
                                                                 promote to VERIFIED with evidence
                                                                 (strict reads only use verified)
  stale                                                          resolutions the parser outgrew
status (resolve): provisional (default for a factor) | verified | ignored_with_reason (default for
         ignore) | no_adjustment_verified | rejected. verified needs --source-type/--source-url.
methods: cost_allocation parent_share=0.957 | direct factor=0.9 | gap (estimate, never verifiable)
         | demerger child_per_parent=1 child_price=261.5
         | rights new=1 held=15 subscription_price=1257 | ignore
"""

import argparse
import os
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg

from algo.data.review import ResolveError, resolve, review_queue, stale_resolutions, verify
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"), help="or set ALGO_DB_URL")
sub = ap.add_subparsers(dest="cmd", required=True)
p = sub.add_parser("list")
p.add_argument("--kind", action="append")
p.add_argument("--symbol", action="append")
p.add_argument("--since", type=date.fromisoformat)
p.add_argument("--all", action="store_true", help="include already-resolved items")
for name in ("resolve", "verify"):
    p = sub.add_parser(name)
    p.add_argument("--symbol", required=True)
    p.add_argument("--ex-date", required=True, type=date.fromisoformat)
    p.add_argument("--kind", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--source-type", help="company_filing | exchange_notice | ...")
    p.add_argument("--source-url")
    p.add_argument("--source-hash")
    if name == "resolve":
        p.add_argument("--status")
        p.add_argument("--method", required=True)
        p.add_argument("--note", required=True)
        p.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
sub.add_parser("stale")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)

with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    try:
        if a.cmd == "list":
            for it in review_queue(conn, kinds=a.kind, symbols=a.symbol, include_resolved=a.all):
                if a.since and it.ex_date < a.since:
                    continue
                obs = f"{it.observed_ratio:.4f}" if it.observed_ratio else "n/a"
                r = it.resolution
                state = "-"
                if r is not None:
                    fac = f"{r.factor:.4f}" if r.factor else "-"
                    state = f"{r.status.upper()} {fac} via {r.method}"
                print(
                    f"{it.ex_date} {it.symbol:12} {it.kind:12} prev={it.prev_close} "
                    f"ex={it.ex_close} observed={obs} | {'; '.join(it.subjects)[:60]} | {state}"
                )
        elif a.cmd == "resolve":
            params = {k: Decimal(v) for k, v in (x.split("=", 1) for x in a.param)}
            res = resolve(
                conn, symbol=a.symbol, ex_date=a.ex_date, kind=a.kind, method=a.method,
                params=params, note=a.note, by=a.by, now=now, status=a.status,
                source_type=a.source_type, source_url=a.source_url, source_hash=a.source_hash,
            )  # fmt: skip
            print(f"stored factor={res.factor}")
            if res.warning:
                print("WARNING:", res.warning)
        elif a.cmd == "verify":
            verify(
                conn, symbol=a.symbol, ex_date=a.ex_date, kind=a.kind, by=a.by, now=now,
                source_type=a.source_type or "", source_url=a.source_url or "",
                source_hash=a.source_hash,
            )  # fmt: skip
            print("verified")
        else:
            for s in stale_resolutions(conn):
                print(s.ex_date, s.symbol, s.kind)
    except ResolveError as e:
        raise SystemExit(f"error: {e}") from e
