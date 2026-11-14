"""NSE backfill, in stages (each resumable / idempotent):
  universe  security master + symbol changes + Nifty 200 snapshot
  actions   corporate actions for every Nifty 200 symbol (full history)
  actions500  as actions, for the Nifty 500 list in the lake; skips symbols with raw actions stored
  actionsall  as actions500, for every active equity in our instrument master (the whole market)
  actionswindow  the whole market in one request, 14 days back to 120 ahead: past and today's join
              the table, announced future ones replace the `upcoming` table (the daily job)
  actionsrefresh  every active equity again (new actions, any never downloaded); a failed symbol
              makes the run exit 1, and new actions that need a person are reported
  reparse   rebuild corporate_action from raw JSON already in the lake (no network)
  bars      daily bars (sec_bhavdata_full, available from 2019-10) over --from/--to
usage: backfill_nse.py --db URL --lake DIR --stage universe|actions|bars [--from D --to D]"""

import argparse
import csv
import io
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg

from algo.core.calendar import nse
from algo.data.corporate_actions import (
    API,
    ReviewKey,
    ingest_symbol,
    load_window,
    new_unresolved,
    refreshed_on,
    reparse_symbol,
    review_keys,
)
from algo.data.instrument_sync import apply_symbol_changes, load_index_snapshot, sync_equities
from algo.data.lake import LocalLake
from algo.data.pipeline import backfill
from algo.data.providers.nse_bhavcopy import NseBhavcopy
from algo.data.providers.nse_client import NseClient
from algo.data.providers.nse_holidays import parse_holidays
from algo.data.providers.nse_security_master import URL as MASTER_URL
from algo.data.providers.nse_security_master import parse_security_master
from algo.data.providers.nse_symbol_changes import parse_index_list, parse_symbol_changes
from algo.data.store.migrate import migrate
from algo.jobs.runner import telegram_alert

ARCH = "https://nsearchives.nseindia.com"
N200 = f"{ARCH}/content/indices/ind_nifty200list.csv"
SYMCHG = f"{ARCH}/content/equities/symbolchange.csv"
HOLIDAYS = "https://www.nseindia.com/api/holiday-master?type=trading"
WARM = "https://www.nseindia.com/companies-listing/corporate-filings-actions"

ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True)
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument(
    "--stage",
    required=True,
    choices=[
        "universe",
        "actions",
        "actions500",
        "actionsall",
        "actionsrefresh",
        "actionswindow",
        "reparse",
        "bars",
    ],
)
ap.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2019, 10, 1))
ap.add_argument("--to", dest="end", type=date.fromisoformat, default=datetime.now(UTC).date())
ap.add_argument(
    "--interval",
    type=float,
    default=1.5,
    help="seconds between NSE requests (NSE drops a client sending over ~330 in 10 minutes)",
)
a = ap.parse_args()

now, lake = datetime.now(UTC), LocalLake(a.lake)
client = NseClient(min_interval=a.interval)


# NSE stops answering one session after about 330 calls (at any pace): start a new session well
# before that, and right after a failure.
NEW_SESSION_EVERY = 150
# Symbols failing one after another mean NSE is not answering: stop instead of hammering it.
MAX_IN_A_ROW = 5


def fresh_session() -> None:
    client.new_session()
    client.warm(WARM)


def log(*m: object) -> None:
    print(datetime.now(UTC).strftime("%H:%M:%S"), *m, flush=True)


def finish_actions(conn: psycopg.Connection, before: set[ReviewKey], failed: int) -> None:
    """Say which NEW actions need a person (to Telegram when set up, else the log) and fail the run
    if any symbol failed, so the scheduler records it instead of calling it ok."""
    found = new_unresolved(conn, before)
    log(f"new actions that need review: {len(found)}")
    if found:
        shown = "; ".join(f"{sym} {kind} ex {ex}" for sym, ex, kind, _subject in found[:10])
        more = f" and {len(found) - 10} more" if len(found) > 10 else ""
        telegram_alert(os.environ)(f"corporate actions: {len(found)} new to review: {shown}{more}")
    if failed:
        log(f"{failed} symbol(s) FAILED: re-run to retry them")
        sys.exit(1)


with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    row = conn.execute("SELECT exchange_id FROM exchange WHERE mic='XNSE'").fetchone()
    if row is None:
        row = conn.execute(
            "INSERT INTO exchange (mic,country,timezone,currency,calendar_id) "
            "VALUES ('XNSE','IN','Asia/Kolkata','INR','NSE') RETURNING exchange_id"
        ).fetchone()
    assert row is not None

    def n200_symbols() -> list[str]:
        raw = client.get(N200)
        lake.put("nse", "index_nifty200", now.date(), raw, url=N200, fetched_at=now)
        return [m.symbol for m in parse_index_list(raw)]

    if a.stage == "universe":
        raw = client.get(MASTER_URL)
        lake.put("nse", "security_master", now.date(), raw, url=MASTER_URL, fetched_at=now)
        r = sync_equities(conn, row[0], parse_security_master(raw), now.date())
        log(f"security master: +{len(r.added)} new, {len(r.missing)} missing")
        raw = client.get(SYMCHG)
        lake.put("nse", "symbol_changes", now.date(), raw, url=SYMCHG, fetched_at=now)
        s = apply_symbol_changes(conn, parse_symbol_changes(raw))
        log(
            f"symbol changes: applied={len(s.applied)} unchanged={len(s.unchanged)} "
            f"not_in_universe={s.not_in_universe} conflicts={s.conflicts}"
        )
        stored, unknown = load_index_snapshot(conn, "NIFTY200", now.date(), n200_symbols())
        log(f"nifty200 snapshot: stored={stored} unknown={unknown}")

    elif a.stage == "actions":
        client.warm(WARM)
        syms = n200_symbols()
        tot_ins = tot_unch = failed = in_a_row = 0
        before = review_keys(conn)
        for i, sym in enumerate(syms, 1):
            if i > 1 and (i - 1) % NEW_SESSION_EVERY == 0:
                fresh_session()
            try:
                r = ingest_symbol(
                    conn, lake, lambda u: client.get(u, accept="application/json"), sym, now
                )
            except Exception as e:  # keep going; failures are listed in the log
                failed += 1
                in_a_row += 1
                fresh_session()  # the session is the usual cause: start another
                log(f"[{i}/{len(syms)}] {sym} FAILED {type(e).__name__}: {e}")
                if in_a_row >= MAX_IN_A_ROW:
                    log(f"{in_a_row} in a row failed: NSE is not answering, stopping")
                    break
                continue
            in_a_row = 0
            if r is None:
                log(f"[{i}/{len(syms)}] {sym} not in instrument master")
                continue
            tot_ins += r.inserted
            tot_unch += r.unchanged
            if i % 20 == 0:
                log(f"[{i}/{len(syms)}] inserted={tot_ins} unchanged={tot_unch}")
        q = "SELECT count(*) FROM corporate_action WHERE status='review'"
        n_review = conn.execute(q).fetchone()[0]
        log(f"actions done: inserted={tot_ins} unchanged={tot_unch} review={n_review}")
        finish_actions(conn, before, failed)

    elif a.stage in ("actions500", "actionsall", "actionsrefresh"):
        if a.stage in (
            "actionsall",
            "actionsrefresh",
        ):  # the whole market: every active equity in our own master
            from algo.data.kite_ingest import master_universe

            listed = [s for s, _, _ in master_universe(conn)]
        else:
            latest = sorted((a.lake / "raw/niftyindices/nifty500_list").glob("dt=*/v*.bin"))[-1]
            listed = [
                r["Symbol"]
                for r in csv.DictReader(io.StringIO(latest.read_bytes().decode("utf-8-sig")))
            ]
        syms = [
            x
            for x in listed
            if not x.startswith("DUMMY")
            and (
                not refreshed_on(lake, x, now.date())  # a refresh asks for everyone not done today
                if a.stage == "actionsrefresh"
                else not (a.lake / f"raw/nse/corporate_actions_{x}").exists()
            )
        ]
        log(f"{a.stage}: {len(listed)} symbols, to fetch: {len(syms)}")
        client.warm(WARM)
        tot_ins = failed = in_a_row = 0
        before = review_keys(conn)
        for i, sym in enumerate(syms, 1):
            if i > 1 and (i - 1) % NEW_SESSION_EVERY == 0:
                fresh_session()
            try:
                r = ingest_symbol(
                    conn, lake, lambda u: client.get(u, accept="application/json"), sym, now
                )
            except (
                Exception
            ) as e:  # keep going; a re-run picks up the failures (nothing was stored for them)
                failed += 1
                in_a_row += 1
                fresh_session()  # the session is the usual cause: start another
                log(f"[{i}/{len(syms)}] {sym} FAILED {type(e).__name__}: {e}")
                if in_a_row >= MAX_IN_A_ROW:
                    log(f"{in_a_row} in a row failed: NSE is not answering, stopping")
                    break
                continue
            in_a_row = 0
            if r is None:
                log(f"[{i}/{len(syms)}] {sym} not in instrument master")
                continue
            tot_ins += r.inserted
            if i % 20 == 0:
                log(f"[{i}/{len(syms)}] inserted={tot_ins} failed={failed}")
        n_review = conn.execute(
            "SELECT count(*) FROM corporate_action WHERE status='review'"
        ).fetchone()[0]
        log(f"{a.stage} done: inserted={tot_ins} failed={failed} review={n_review}")
        finish_actions(conn, before, failed)

    elif a.stage == "actionswindow":
        today = now.date()
        url = (
            f"{API}?index=equities&from_date={today - timedelta(days=14):%d-%m-%Y}"
            f"&to_date={today + timedelta(days=120):%d-%m-%Y}"
        )
        before = review_keys(conn)
        client.warm(WARM)
        try:
            body = client.get(url, accept="application/json")
        except Exception as e:
            log(f"window request FAILED {type(e).__name__}: {e}")
            sys.exit(1)
        m = lake.put("nse", "corporate_actions_window", today, body, url=url, fetched_at=now)
        r = load_window(conn, body, today, m.checksum, now)
        log(
            f"window done: inserted={r.inserted} unchanged={r.unchanged} upcoming={r.upcoming}"
            f" unknown symbols={len(r.unknown_symbols)} {r.unknown_symbols[:8]}"
        )
        finish_actions(conn, before, 0)

    elif a.stage == "reparse":
        q = (
            "SELECT DISTINCT al.source_symbol FROM index_snapshot i JOIN instrument_alias al "
            "USING (instrument_id) WHERE i.index_id='NIFTY200' AND al.source='nse' "
            "AND al.valid_to IS NULL ORDER BY 1"
        )
        syms = [r[0] for r in conn.execute(q)]
        ins = rep = 0
        for sym in syms:
            r = reparse_symbol(conn, lake, sym, now)
            if r is not None:
                ins += r.inserted
                rep += r.replaced
        n_review = conn.execute(
            "SELECT count(*) FROM corporate_action WHERE status='review'"
        ).fetchone()[0]
        log(f"reparse done: symbols={len(syms)} rows={ins} replaced={rep} review={n_review}")

    else:
        client.warm(WARM)
        try:
            raw = client.get(HOLIDAYS, accept="application/json")
            lake.put("nse", "holiday_master", now.date(), raw, url=HOLIDAYS, fetched_at=now)
            hol = parse_holidays(raw)
            n_hol, sp = len(hol.weekday_holidays), hol.special_review
            log(f"holidays (current year): {n_hol}, special: {sp}")
            cal = nse(hol.weekday_holidays)
        except Exception as e:
            log(f"holiday feed unavailable ({e}); relying on 404 detection")
            cal = nse()
        prov = NseBhavcopy(client.get, cal)
        total: dict[str, int] = {}

        def progress(d: date, status: str) -> None:
            total[status] = total.get(status, 0) + 1
            if sum(total.values()) % 25 == 0:
                log(f"{d} {total}")

        out = backfill(conn, lake, prov, "bhav", a.start, a.end, now, progress=progress)
        log(f"bars done: {out}")
    sys.stdout.flush()
