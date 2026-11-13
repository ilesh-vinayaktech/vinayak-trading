# ruff: noqa: E501
"""Read when each special session really traded from the stored 1-minute bars (algo.data.sessions.observed_intervals) and record it
on the session in config/exchange_sessions.json as `observed`. Where the session's hours are VERIFIED from an NSE circular, the
observation must agree (open, close, and a gap in a split session): a disagreement stops the run and nothing is written.
usage: observe_sessions.py [--db URL] [--from 2016-01-01]"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import psycopg

from algo.data.sessions import observed_intervals

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--file", type=Path, default=Path("config/exchange_sessions.json"))
ap.add_argument("--from", dest="since", type=date.fromisoformat, default=date(2016, 1, 1))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
# Sessions with no NSE circular found: marked as special sessions, with their hours read from the minute bars (status OBSERVED).
# date: (kind, what we know, hours override or None to use the single observed interval)
OBSERVED_ONLY = {
    "2016-10-30": ("MUHURAT", "Diwali Muhurat session (Zerodha bulletin 53006 and press: 6.30-7.30 pm; no NSE circular found). All instruments trade 18:30-19:16, 17 instruments to 19:30", ("18:30", "19:30")),
    "2017-07-10": ("SPECIAL", "NSE technical outage: trading halted in the morning and resumed 12:30 (press; no NSE circular found)", None),
    "2021-02-24": ("SPECIAL", "NSE outage: halted 11:40, resumed in the afternoon, trading hours extended to 17:00 (SEBI press release 8/2021)", None),
    "2024-11-01": ("MUHURAT", "Diwali Muhurat session, 18:00-19:00 (NSE notification as reported by AIR News and brokers; no NSE circular found)", None),
}  # fmt: skip
doc = json.loads(a.file.read_text())
for day, (kind, what, _h) in OBSERVED_ONLY.items():
    if not any(x["date"] == day for x in doc["sessions"]):
        doc["sessions"].append(
            {"date": day, "weekday": date.fromisoformat(day).strftime("%A"), "kind": kind}
        )
    e = next(x for x in doc["sessions"] if x["date"] == day)
    if not e.get("kind_status", "").startswith("CONFIRMED"):
        e["kind"], e["kind_status"] = kind, f"OBSERVED ({what})"
        e["evidence"] = "stored 1-minute bars (see `observed`); " + what
doc["sessions"].sort(key=lambda x: x["date"])
bad: list[str] = []
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as conn:
    for s in doc["sessions"]:
        d = date.fromisoformat(s["date"])
        if d < a.since:
            continue
        rows = conn.execute(
            "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::time, count(*) FROM bar_1m"
            " WHERE ts >= (%s::date::timestamp AT TIME ZONE 'Asia/Kolkata') AND ts < ((%s::date + 1)::timestamp AT TIME ZONE 'Asia/Kolkata') GROUP BY 1",
            (d, d)).fetchall()  # fmt: skip
        if not rows:
            print(f"{d}  no minute bars")
            continue
        counts = {t: n for t, n in rows}
        fmt = lambda ivs: [[t.strftime("%H:%M") for t in iv] for iv in ivs]  # noqa: E731
        core = fmt(
            observed_intervals(counts)
        )  # minutes with >= 20% of the busiest minute's instruments
        got = fmt(
            observed_intervals(counts, share=0.0)
        )  # any bar at all: a thin tail is real trading in a few names
        tail = sum(1 for t, n in counts.items() if n < max(counts.values()) * 0.2)
        s["observed"] = {"intervals": got, "core_intervals": core, "instruments_at_peak": max(counts.values()), "thin_minutes_ignored": tail,
                         "source": "stored 1-minute bars (Kite). intervals = minutes with any bar; core_intervals = minutes where at least 20% of the busiest minute's instruments have a bar"}  # fmt: skip
        if s["date"] in OBSERVED_ONLY:
            hours = OBSERVED_ONLY[s["date"]][2] or (got[0] if len(got) == 1 else None)
            if hours:
                s["hours"] = list(hours)
                s.pop("intervals", None)
                s["hours_status"] = (
                    f"OBSERVED (stored minute bars: first bar {hours[0]}, last bar ends {hours[1]})"
                )
            else:
                s["hours"], s["intervals"] = None, got
                s["hours_status"] = (
                    "UNKNOWN (observed in several intervals: "
                    + ", ".join(f"{x}-{y}" for x, y in got)
                    + "; the calendar holds one interval per day)"
                )
        if s["date"] in OBSERVED_ONLY:
            want = None
        elif s["hours_status"].startswith("VERIFIED"):
            want = [list(s["hours"])]
        elif s.get("intervals"):
            want = s["intervals"]
        else:
            want = None
        verdict = (
            "no circular to compare"
            if want is None
            else "agrees with the circular"
            if got == want
            else "DISAGREES"
        )
        if verdict == "DISAGREES":
            bad.append(f"{d}: observed {got}, circular {want}")
        print(
            f"{d}  observed {got}  ({max(counts.values())} instruments, {tail} thin minutes)  {verdict}"
        )
if bad:
    sys.exit("stopped, nothing written:\n  " + "\n  ".join(bad))
a.file.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
