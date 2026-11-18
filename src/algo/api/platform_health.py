"""One verdict on whether the platform is healthy, from signals we already have: how current the
price data is, how the scheduled jobs last ended, quarantined loads and the Kite connection. Pure:
it is given those signals and the time (no clock, no database) and returns every reason.

DOWN means the data the research and paper trading stand on is not there or is badly behind;
ATTENTION means something should be looked at but the platform still works."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

_CAL = re.compile(r"^(?:(\S+) )?\*-\*-(\*|\d{2}) (\d{2}:\d{2}) Asia/Kolkata$")
_NEVER_NAMED = 3  # job names listed in the "never ran" reason before "and N more"


def max_age_days(calendar: str) -> int:
    """How long a job may go without succeeding before it counts as overdue: a missed run plus slack
    (weekday jobs span a weekend and a holiday; weekly and monthly ones a missed week or month)."""
    m = _CAL.match(calendar)
    if m is None:
        return 2
    days, day, _ = m.groups()
    if day != "*":
        return 35
    if days is None:
        return 2
    return 5 if days == "Mon..Fri" else 9


_STEP = re.compile(
    r"^(\S+) \*-\*-\* (\d{2})\.\.(\d{2}):00/(\d+):00 Asia/Kolkata$"
)  # "Mon..Fri *-*-* 09..15:00/5:00 Asia/Kolkata"
# jobs on several schedules (news, live-data-check) run hourly at least: 6 h without success is late
FREQUENT_AFTER = timedelta(hours=6)


def is_frequent(calendar: str) -> bool:
    return ";" in calendar


def schedule_text(calendar: str) -> str:
    if is_frequent(calendar):
        parts = [p.strip() for p in calendar.split(";")]
        step = _STEP.match(parts[0])
        if step and len(parts) == 3:
            days, start, end, every = step.groups()
            hours = f"{start}:00 to {end}:55 IST"
            return f"{days} every {every} min, {hours}; hourly at other times and at weekends"
        return "; ".join(schedule_text(p) for p in parts)
    m = _CAL.match(calendar)
    if m is None:
        return calendar
    days, day, time = m.groups()
    if day != "*":
        return f"Day {int(day)} of the month, {time} IST"
    return f"{days} {time} IST" if days else f"Daily {time} IST"


def _span(now: datetime, then_iso: str) -> str:
    minutes = int((now - datetime.fromisoformat(then_iso)).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h"
    return f"{minutes // (24 * 60)} d"


def _reason(level: str, text: str) -> dict[str, str]:
    return {"level": level, "text": text}


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _job_reasons(now: datetime, jobs: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    failed, overdue, never = [], [], []
    for j in jobs:
        last = j["last_run"]
        if last is None:
            never.append(j["name"])
        elif last["status"] == "failed":
            after = f" after {last['attempts']} attempts" if last["attempts"] > 1 else ""
            why = f": {last['detail']}" if last["detail"] else ""
            failed.append(
                _reason(
                    "attention",
                    f"{j['name']} failed {_span(now, last['finished_at'])} ago{after}{why}.",
                )
            )
        elif j["last_success_at"] is not None:
            age = now - datetime.fromisoformat(j["last_success_at"])
            limit = (
                FREQUENT_AFTER
                if is_frequent(j["calendar"])
                else timedelta(days=max_age_days(j["calendar"]) + 1)
            )  # a daily job: overdue after more than its limit in whole days
            if age >= limit:
                overdue.append(
                    _reason(
                        "attention",
                        f"{j['name']} has not succeeded for {_span(now, j['last_success_at'])}"
                        f" (it runs {schedule_text(j['calendar'])}).",
                    )
                )
    out = failed + overdue
    if never:
        shown = ", ".join(never[:_NEVER_NAMED])
        more = f" and {len(never) - _NEVER_NAMED} more" if len(never) > _NEVER_NAMED else ""
        n = len(never)
        out.append(
            _reason(
                "attention",
                f"{n} scheduled {_plural(n, 'job has', 'jobs have')} never run: {shown}{more}.",
            )
        )
    return out


def assess(
    *,
    now: datetime,
    freshness: Mapping[str, Any] | None,
    jobs: Sequence[Mapping[str, Any]],
    quarantined: Sequence[str],
    kite_state: str | None,
    checks: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """{"status": OK | ATTENTION | DOWN, "reasons": [{"level": attention | down, "text": ...}]}."""
    reasons: list[dict[str, str]] = []
    if freshness is None:
        reasons.append(_reason("down", "No price data is loaded yet."))
    elif freshness["status"] != "CURRENT":
        n = freshness["sessions_behind"]
        reasons.append(
            _reason(
                "down" if n >= 2 else "attention",
                f"Price data is {n} {_plural(n, 'session', 'sessions')} behind"
                f" (latest bar session {freshness['latest_bar_session']}).",
            )
        )
    if quarantined:
        n = len(quarantined)
        reasons.append(
            _reason(
                "attention",
                f"{n} {_plural(n, 'partition is', 'partitions are')} quarantined:"
                f" {', '.join(quarantined)}.",
            )
        )
    if kite_state is None:
        reasons.append(
            _reason(
                "attention",
                "No Kite data feed is connected: the loaders and the live feed cannot run.",
            )
        )
    elif kite_state == "expired":
        reasons.append(
            _reason(
                "attention",
                "The Kite session has expired: log in on the Kite page so the loaders and the"
                " live feed can run.",
            )
        )
    elif kite_state != "connected":
        reasons.append(
            _reason(
                "attention",
                "Kite is saved but not connected: log in on the Kite page so the loaders and the"
                " live feed can run.",
            )
        )
    reasons += _job_reasons(now, jobs)
    reasons += [
        _reason(c["level"], c["text"]) for c in checks
    ]  # the live-data checks (index quotes, news, Laya, live-zone baseline, lists)
    status = (
        "DOWN" if any(r["level"] == "down" for r in reasons) else "ATTENTION" if reasons else "OK"
    )
    return {"status": status, "reasons": reasons}
