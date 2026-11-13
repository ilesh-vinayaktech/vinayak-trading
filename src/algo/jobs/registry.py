# ruff: noqa: E501
"""The scheduled jobs (TODO B) and the systemd user units that run them. Times are Indian time, trading days only
(weekday timers; holidays are handled by each job's own freshness check, which counts only sessions)."""

from __future__ import annotations

from algo.jobs.runner import Job

_PY = ("uv", "run", "python")
_BARS = (*_PY, "scripts/backfill_nse.py", "--db", "{db}", "--lake", "data/lake", "--stage", "bars")
_STALE = (*_PY, "scripts/check_stale.py")
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
        "kite-reconcile",
        f"{WEEKDAYS} *-*-* 20:00 Asia/Kolkata",
        ((*_PY, "scripts/reconcile_kite_prices.py"),),
        "Compare the stored Kite daily candles with bhavcopy (database only: needs no Kite session)",
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
                "actions",
            ),
        ),
        "Re-fetch corporate actions for the Nifty 200 (about 5 minutes); new ones that need a person are reported",
        retries=1,
        retry_wait_s=600,
    ),
    Job(
        "corporate-actions-weekly",
        "Sat *-*-* 05:00 Asia/Kolkata",
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
        "Re-fetch corporate actions for every active equity (about 2 hours at a polite pace); resumes after a throttle; new ones that need a person are reported",
        timeout_s=4 * 3600,
        retries=6,  # NSE throttles a client after about 330 requests in 10 minutes; the stage resumes where it stopped
        retry_wait_s=900,
    ),
    Job(
        "kite-daily-candles",
        f"{WEEKDAYS} *-*-* 19:30 Asia/Kolkata",
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
            ),
        ),  # fmt: skip
        "Kite daily candles for the mapped instruments (exit 3 = session expired, 1 = some stock failed; alerted)",
        timeout_s=2
        * 3600,  # about 2,600 stocks at 2 requests a second is 25 minutes; the default 2 s spacing would be 87
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
                "{d30}",
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
        "Nightly database dump, 14 days kept (the lake is not backed up: needs a destination)",
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
