# ruff: noqa: E501
"""The scheduled jobs (TODO B) and the systemd user units that run them. Times are Indian time, trading days only
(weekday timers; holidays are handled by each job's own freshness check, which counts only sessions).
A date window ({d1} {d7} {d30} {d120}) reaches back to the day before the job's last successful run when runs were missed, so the next
run covers everything since then (see runner._windows). Jobs that read a fixed window inside their own script, or that NSE publishes
only the latest of (deals, FII/DII), cannot catch up this way."""

from __future__ import annotations

from algo.jobs.runner import Job

_PY = ("uv", "run", "python")
_BARS = (*_PY, "scripts/backfill_nse.py", "--db", "{db}", "--lake", "data/lake", "--stage", "bars")
_STALE = (*_PY, "scripts/check_stale.py", "--record")
WEEKDAYS = "Mon..Fri"

JOBS: tuple[Job, ...] = (
    Job(
        "kite-login-reminder",
        f"{WEEKDAYS} *-*-* 08:15 Asia/Kolkata",
        (("true",),),
        "Alert if there is no valid Kite session before the feed starts (the login is manual)",
        needs_kite=True,
    ),
    Job(
        "bhavcopy-daily",
        f"{WEEKDAYS} *-*-* 18:30 Asia/Kolkata",
        ((*_BARS, "--from", "{d7}"), _STALE),
        "Load the daily bhavcopy; retries every 10 min for 2 h until the newest bar is current",
        retries=12,
    ),
    Job(
        "data-completeness",
        f"{WEEKDAYS} *-*-* 21:15 Asia/Kolkata",
        ((*_PY, "scripts/check_completeness.py", "--db", "{db}", "--record"),),
        "Alert on a quarantined bhavcopy, an open weekday with no daily bars, or a session with under 90% of the usual number of bars (after the retries and the gap sweep have had their chance)",
    ),
    Job(
        "regulatory-check",
        f"{WEEKDAYS} *-*-* 08:00 Asia/Kolkata",
        ((*_PY, "scripts/regulatory.py", "--db", "{db}", "status"),),
        "Alert when a regulatory rule live trading needs (order-rate limit, order types, tagging, static IP) is not recorded or was last verified over 30 days ago: live stays blocked until it is checked and recorded again",
    ),
    Job(
        "platform-boot",
        f"{WEEKDAYS} *-*-* 08:50 Asia/Kolkata",
        ((*_PY, "scripts/platform_boot.py", "--db", "{db}"),),
        "Before the market opens: INITIALIZING -> DATA_VALIDATION -> READY -> PAPER, each step recorded, only if the daily data is current, a Kite session exists and the order log, orders and positions all agree; alerts when the platform does not reach PAPER (a strategy then cannot propose while ALGO_REQUIRE_PLATFORM_READY=1)",
    ),
    Job(
        "heartbeat-check",
        f"{WEEKDAYS} *-*-* 09..15:*:00 Asia/Kolkata",
        ((*_PY, "scripts/check_heartbeats.py", "--db", "{db}"),),
        "Every minute in market hours: alert when a process that should be running (the live feed, and the study worker where it is expected) has never reported, gone silent, is degraded or has stopped",
    ),
    Job(
        "paper-run",
        f"{WEEKDAYS} *-*-* 21:30 Asia/Kolkata",
        ((*_PY, "scripts/run_paper.py", "--db", "{db}", "--sandbox"),),
        "The evening decision for every enabled paper account on the newest session, each strategy in its sandboxed worker (after the data jobs and checks; a run that cannot decide, or errors, alerts; a strategy that breaks a rule is halted and paused); proposals wait for the owner's approval",
    ),
    Job(
        "paper-orders",
        f"{WEEKDAYS} *-*-* 09..15:00/5:00 Asia/Kolkata",
        ((*_PY, "scripts/paper_orders.py", "--db", "{db}"),),
        "Every five minutes in market hours: fill approved paper orders at the next live open (needs the live feed) and expire the ones that ran out of time",
    ),
    Job(
        "paper-reconcile",
        f"{WEEKDAYS} *-*-* 09..15:*:30 Asia/Kolkata",
        ((*_PY, "scripts/paper_reconcile.py", "--db", "{db}"),),
        "Every minute in market hours and once after the close (the half-minute keeps it clear of paper-orders): close the positions of an account whose kill switch is FLATTEN, then check the OMS log, the paper orders and the book against each other; a mismatch pauses the strategy and alerts",
    ),
    Job(
        "compute-features",
        "*-*-* 23:45 Asia/Kolkata",
        ((*_PY, "scripts/compute_features.py", "--db", "{db}"),),
        "Materialise every USABLE feature month by month against the newest data freeze; completed months are skipped, a paper run or market hours pause it at a month boundary, and it refuses when the input data is not ready",
        timeout_s=6 * 3600,
    ),
    Job(
        "price-continuity",
        f"{WEEKDAYS} *-*-* 19:45 Asia/Kolkata",
        ((*_PY, "scripts/check_price_continuity.py", "--db", "{db}", "--record"),),
        "Alert on a raw NSE close that jumped more than 20% with no corporate action recorded (an action the parser could not price, or a missing one)",
    ),
    Job(
        "kite-reconcile",
        f"{WEEKDAYS} *-*-* 20:00 Asia/Kolkata",
        ((*_PY, "scripts/reconcile_kite_prices.py", "--record"),),
        "Compare the stored Kite daily candles with bhavcopy (database only: needs no Kite session); alerts on stocks that newly disagree, not on the known backlog",
    ),
    Job(
        "gap-nightly",
        "*-*-* 22:00 Asia/Kolkata",
        ((*_BARS, "--from", "{d30}"),),
        "Re-sweep the last 30 days for missing sessions",
    ),
    Job(
        "gap-weekly",
        "Sun *-*-* 03:00 Asia/Kolkata",
        ((*_BARS,),),
        "Deep sweep from 2019-10 (resumable; loaded days are skipped)",
        timeout_s=6 * 3600,
    ),
    Job(
        "calendar-weekly",
        "Sun *-*-* 07:00 Asia/Kolkata",
        ((*_PY, "scripts/calendar_sync.py"),),
        "Sync the NSE holiday calendar",
    ),
    Job(
        "universe-daily",
        f"{WEEKDAYS} *-*-* 19:00 Asia/Kolkata",
        (
            (
                *_PY,
                "scripts/backfill_nse.py",
                "--db",
                "{db}",
                "--lake",
                "data/lake",
                "--stage",
                "universe",
            ),
        ),
        "Security master, new listings, symbol changes and the Nifty 200 snapshot",
    ),
    Job(
        "corporate-actions-daily",
        f"{WEEKDAYS} *-*-* 19:15 Asia/Kolkata",
        (
            (
                *_PY,
                "scripts/backfill_nse.py",
                "--db",
                "{db}",
                "--lake",
                "data/lake",
                "--stage",
                "actionswindow",
            ),
        ),
        "Corporate actions for the whole market in one request (last 14 days to 120 days ahead): new ones join the table, announced future ones are listed; new ones that need a person are reported",
        retries=2,
        retry_wait_s=600,
    ),
    Job(
        "corporate-actions-monthly",
        "*-*-08 05:00 Asia/Kolkata",
        (
            (
                *_PY,
                "scripts/backfill_nse.py",
                "--db",
                "{db}",
                "--lake",
                "data/lake",
                "--stage",
                "actionsrefresh",
                "--interval",
                "3.0",
            ),
        ),  # fmt: skip
        "Rebuild corporate actions from NSE's full history for every active equity (about 2 hours at a polite pace; resumes after a throttle): catches revisions made after an ex-date and anything the daily job missed",
        timeout_s=4 * 3600,
        retries=6,  # NSE throttles a client after about 330 requests in 10 minutes; the stage resumes where it stopped
        retry_wait_s=900,
    ),
    Job(
        "nse-deals-fiidii",
        f"{WEEKDAYS} *-*-* 18,19,20,21:20 Asia/Kolkata",
        (
            (*_PY, "scripts/ingest_nse_intel.py", "deals", "--db", "{db}"),
            (*_PY, "scripts/ingest_nse_intel.py", "fiidii", "--db", "{db}"),
        ),
        "Bulk and block deals and FII/DII cash flows: NSE publishes only the latest session, in the evening, at no fixed minute, so it is polled four times; a re-poll of what is stored changes nothing",
        retries=2,
        retry_wait_s=300,
    ),
    Job(
        "nse-insider-hourly",
        f"{WEEKDAYS} *-*-* 09..21:10 Asia/Kolkata",
        ((*_PY, "scripts/ingest_nse_intel.py", "insider", "--db", "{db}"),),
        "Insider (SEBI PIT) trade disclosures: NSE lists one row per filing (a new list since 2026-05-03); companies file through the day, so the last 7 days are re-listed hourly and the file of each NEW filing is read for person, quantity and value",
        retries=2,
        retry_wait_s=300,
    ),
    Job(
        "nse-shareholding-daily",
        f"{WEEKDAYS} *-*-* 20:40 Asia/Kolkata",
        ((*_PY, "scripts/ingest_nse_intel.py", "shareholding", "--db", "{db}"),),
        "Shareholding patterns: a quarterly filing (within 21 days of quarter end, revisions any time); one request lists every company's latest, new and revised filings are stored",
        retries=2,
        retry_wait_s=300,
    ),
    Job(
        "nse-shareholding-split",
        "*-*-* 22:40 Asia/Kolkata",
        ((*_PY, "scripts/ingest_nse_intel.py", "split", "--db", "{db}", "--limit", "600"),),
        "Read the XBRL of new shareholding filings for the FII / DII / mutual fund / retail split (600 a night at about one a second; the first backfill of about 2,400 filings takes four nights, newest first; a filing that cannot be read is recorded and not retried)",
        timeout_s=2 * 3600,
        retries=2,
        retry_wait_s=900,
    ),
    Job(
        "kite-daily-candles",
        f"{WEEKDAYS} *-*-* 17:00 Asia/Kolkata",
        (
            (
                *_PY,
                "scripts/kite_load_days.py",
                "--db",
                "{db}",
                "--from",
                "{d1}",
                "--interval",
                "0.5",
            ),
        ),  # fmt: skip
        "The Kite daily candle for the mapped instruments, today and any day missed since the last run (the -BE series are skipped; the close is provisional until the morning revise; exit 3 = session expired, 1 = some stock failed; alerted)",
        timeout_s=2
        * 3600,  # about 2,400 stocks at 2 requests a second is 20 minutes; the default 2 s spacing would be 80
        needs_kite=True,
    ),
    Job(
        "kite-daily-revise",
        f"{WEEKDAYS} *-*-* 09:05 Asia/Kolkata",
        (
            (
                *_PY,
                "scripts/kite_load_days.py",
                "--db",
                "{db}",
                "--from",
                "{d7}",
                "--interval",
                "0.5",
                "--revise",
            ),
        ),  # fmt: skip
        "Re-read the last week of Kite daily candles and keep the final values: yesterday's evening candle is provisional, a changed candle is stored as the next dataset version and the history is kept (also fills a missed day); frozen days are never touched",
        timeout_s=2 * 3600,
        needs_kite=True,
    ),
    Job(
        "kite-index-daily",
        f"{WEEKDAYS} *-*-* 17:30 Asia/Kolkata",
        ((*_PY, "scripts/load_index_days.py", "--db", "{db}", "--from", "{d7}"),),
        "Daily OHLC of every NSE and BSE index (about 207, for trend setup): the last 7 days are re-read and upserted, so the evening's provisional candle is replaced by the final one and a missed day is filled; no volume (indexes have none)",
        needs_kite=True,
    ),
    Job(
        "fundamentals-daily",
        f"{WEEKDAYS} *-*-* 21:00 Asia/Kolkata",
        (
            (
                *_PY,
                "scripts/ingest_fundamentals.py",
                "--db",
                "{db}",
                "--integrated",
                "--since",
                "{d120}",  # compared with the QUARTER-END date of a filing, so it must reach back past the last quarter end
            ),
            (*_PY, "scripts/backfill_fundamental_facts.py", "--db", "{db}"),
        ),
        "Latest results (resumable sweep of recent filings), then the full set of figures",
        timeout_s=2 * 3600,
    ),
    Job(
        "screener-refresh",
        f"{WEEKDAYS} *-*-* 21:30 Asia/Kolkata",
        ((*_PY, "scripts/refresh_screener.py", "--db", "{db}"),),
        "Rebuild the stored stock-screener table from the day's bars and results (after both have loaded)",
        timeout_s=1800,
    ),
    Job(
        "market-zone",
        f"{WEEKDAYS} *-*-* 21:45 Asia/Kolkata",
        (
            (*_PY, "scripts/build_market_zone.py", "--db", "{db}"),
            (*_PY, "scripts/build_score_history.py", "--db", "{db}"),
            (*_PY, "scripts/build_predictions.py", "--db", "{db}"),
        ),
        "Market breadth, the fear/greed score and the bull/bear regime for the day, the day's point-in-time swing scores, then tonight's market and sector forecasts and the resolution of earlier ones (after the bars and the screener refresh)",
        timeout_s=1800,
    ),
    Job(
        "benchmarks-daily",
        f"{WEEKDAYS} *-*-* 07:30 Asia/Kolkata",
        ((*_PY, "scripts/sync_benchmarks.py", "--db", "{db}"),),
        "Index total-return series (Nifty 50/200 and every broad, sector and thematic index) up to yesterday: capture, ingest, validate; a failed series alerts, the rest still load",
        timeout_s=3 * 3600,
    ),
    Job(
        "constituents-weekly",
        "Sat *-*-* 10:00 Asia/Kolkata",
        ((*_PY, "scripts/capture_current_lists.py", "--lake", "data/lake"),),
        "Store today's official index constituent lists in the lake",
    ),
    Job(
        "amfi-caps-monthly",
        "*-*-05 10:00 Asia/Kolkata",
        ((*_PY, "scripts/load_amfi_caps.py"),),
        "AMFI market-cap rankings (picks up the Jun/Dec lists when published; safe to repeat)",
    ),
    Job(
        "cost-sources-monthly",
        "*-*-01 10:00 Asia/Kolkata",
        ((*_PY, "scripts/capture_cost_sources.py", "--lake", "data/lake"),),
        "Re-capture the official fee documents into the lake",
    ),
    Job(
        "db-backup",
        "*-*-* 23:00 Asia/Kolkata",
        (
            (
                "bash",
                "-c",
                "set -o pipefail; mkdir -p data/backups && docker exec algo-dev pg_dump -U postgres -Fc algo > data/backups/algo_{today}.part && mv data/backups/algo_{today}.part data/backups/algo_{today}.dump && find data/backups -name 'algo_*.dump' -mtime +14 -delete",
            ),
        ),
        "Nightly database dump, 14 days kept (the lake is mirrored by lake-backup once ALGO_LAKE_BACKUP_DIR is set)",
    ),
    Job(
        "lake-backup",
        "*-*-* 23:15 Asia/Kolkata",
        ((*_PY, "scripts/backup_lake.py", "--lake", "data/lake"),),
        "Mirror the raw lake to ALGO_LAKE_BACKUP_DIR (add-only, verified, a changed file is an error); alerts until a destination is set",
        timeout_s=3 * 3600,
    ),
    Job(
        "data-freshness",
        f"{WEEKDAYS} *-*-* 09:00 Asia/Kolkata",
        (_STALE,),
        "Alert if the newest bar is behind the latest session",
    ),
    Job(
        "disk-check",
        "*-*-* 06:00 Asia/Kolkata",
        (("bash", "-c", "test $(df --output=pcent . | tail -1 | tr -dc 0-9) -lt 90"),),
        "Alert when the disk holding the data is 90% full",
    ),
)

SERVICE = """[Unit]
Description=Algo scheduled job %i

[Service]
Type=oneshot
WorkingDirectory={app}
TimeoutStartSec=infinity
ExecStart=/bin/bash -c 'set -a; . ./.env; set +a; exec {uv} run python scripts/run_job.py %i'
"""

TIMER = """[Unit]
Description={description}

[Timer]
OnCalendar={calendar}
Persistent=true
Unit=algo-job@{name}.service

[Install]
WantedBy=timers.target
"""


def render_units(app: str, uv: str, jobs: tuple[Job, ...] = JOBS) -> dict[str, str]:
    """File name -> content: one service template and one timer per job."""
    out = {"algo-job@.service": SERVICE.format(app=app, uv=uv)}
    for j in jobs:
        out[f"algo-job-{j.name}.timer"] = TIMER.format(
            description=j.description, calendar=j.calendar, name=j.name
        )
    return out
