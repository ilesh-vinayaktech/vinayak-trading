# ruff: noqa: E501
"""One runner for every scheduled job: a lock (no overlap), a log file, retries, and an alert on failure or skip.

A job is a list of steps (commands); the first failing step fails the attempt and the whole job is retried, so "retry until
published" is just [load, check-data-is-current] with retries. Exit code 75 from a step means "skipped, not failed" (e.g. no
Kite session): alerted, not retried. Times and the clock are injected; nothing here reads the system clock.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from algo.core.clock import Clock
from algo.data.providers.kite_session import load_token

IST = ZoneInfo("Asia/Kolkata")
EX_SKIP = 75
Alert = Callable[[str], None]


@dataclass(frozen=True)
class JobRun:
    """How one run of a job ended (kept so the portal can show when each job last ran)."""

    job: str
    started_at: datetime
    finished_at: datetime
    status: str  # ok | failed | skipped
    attempts: int
    detail: str  # why it failed or was skipped; empty when ok


Record = Callable[[JobRun], None]


@dataclass(frozen=True)
class Job:
    name: str
    calendar: str  # systemd OnCalendar, Indian time
    steps: tuple[tuple[str, ...], ...]  # {today} {d7} {d30} (IST dates) and {db} are filled in
    description: str
    timeout_s: int = 3600  # per step
    retries: int = 0
    retry_wait_s: int = 600
    needs_kite: bool = False


def _feed_ok(session_ok: Callable[[datetime], bool] | None, now: datetime) -> bool:
    """The portal's data feed counts as a Kite session; a check that cannot be made is "no session"."""
    if session_ok is None:
        return False
    try:
        return session_ok(now)
    except Exception:  # noqa: BLE001  the database being down must skip the job, not crash the runner
        return False


def telegram_alert(env: Mapping[str, str]) -> Alert:
    """Telegram if ALGO_TELEGRAM_TOKEN and ALGO_TELEGRAM_CHAT are set; otherwise the text goes to stderr (journal)."""
    token, chat = env.get("ALGO_TELEGRAM_TOKEN"), env.get("ALGO_TELEGRAM_CHAT")

    def send(text: str) -> None:
        if not (token and chat):
            print(f"ALERT: {text}", flush=True)
            return
        body = json.dumps({"chat_id": chat, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            body,
            {"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=20).read()  # noqa: S310 (fixed https URL)
        except OSError as e:  # an alert that cannot be sent must not hide the job result
            print(f"ALERT (telegram failed: {e}): {text}", flush=True)

    return send


def run_job(
    job: Job,
    *,
    clock: Clock,
    alert: Alert,
    lock_dir: Path,
    log_dir: Path,
    env: Mapping[str, str] | None = None,
    token_file: Path = Path("data/secrets/kite_token.json"),
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    record: Record = lambda _run: None,
    session_ok: Callable[[datetime], bool] | None = None,
) -> int:
    """0 = ok, 1 = failed, EX_SKIP = skipped, 0 with no work = another run holds the lock."""
    env = os.environ if env is None else env
    now = clock.now()

    def done(status: str, attempts: int, detail: str = "") -> None:
        try:
            record(JobRun(job.name, now, clock.now(), status, attempts, detail))
        except Exception as e:  # noqa: BLE001  a history that cannot be written must not hide the result
            print(f"could not record the run of {job.name}: {e}", flush=True)

    today = now.astimezone(IST).date()
    fill = {
        "today": today.isoformat(),
        "d7": (today - timedelta(days=7)).isoformat(),
        "d30": (today - timedelta(days=30)).isoformat(),
        "db": env.get("ALGO_DB_URL", ""),
    }
    lock_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / f"{job.name}.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0  # the previous run is still going; do not stack a second one
        if job.needs_kite and load_token(token_file, now) is None and not _feed_ok(session_ok, now):
            alert(
                f"{job.name}: SKIPPED, no valid Kite session (log in via the portal; tokens expire 06:00 IST)"
            )
            done("skipped", 0, "no valid Kite session")
            return EX_SKIP
        log = log_dir / f"{job.name}_{today:%Y%m%d}.log"
        last = ""
        for attempt in range(job.retries + 1):
            if attempt:
                sleep(job.retry_wait_s)
            code = 0
            with log.open("ab") as f:
                for step in job.steps:
                    argv = [a.format(**fill) for a in step]
                    f.write(f"$ {' '.join(step)}\n".encode())  # the template: {db} holds a password
                    f.flush()
                    try:
                        code = run(
                            argv,
                            stdout=f,
                            stderr=subprocess.STDOUT,
                            timeout=job.timeout_s,
                            env=dict(env),
                        ).returncode
                    except subprocess.TimeoutExpired:
                        code = 124
                    if code:
                        last = (
                            f"{next((a for a in step if a.endswith('.py')), step[0])} exited {code}"
                        )
                        break
            if code == 0:
                done("ok", attempt + 1)
                return 0
            if code == EX_SKIP:
                alert(f"{job.name}: SKIPPED ({last}). Log: {log}")
                done("skipped", attempt + 1, last)
                return EX_SKIP
        alert(f"{job.name}: FAILED after {job.retries + 1} attempt(s): {last}. Log: {log}")
        done("failed", job.retries + 1, last)
        return 1
