# ruff: noqa: E501
"""Record the NSE circulars that confirm the kind and hours of special sessions in config/exchange_sessions.json. Each circular is
downloaded, kept untouched in the lake (nse / session_circulars) and CHECKED: its text must carry the session date and the quoted
times, otherwise nothing is written. Sessions with no circular found stay UNCONFIRMED / UNKNOWN. usage: record_session_circulars.py [--lake data/lake]"""

import argparse
import json
import re
import subprocess
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

from algo.data.lake import LocalLake

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
SPLIT = "UNKNOWN (two normal-market intervals {i}; the calendar holds one interval per day)"
DR = ("MSD59999", "MSD60677", "MSD61893")
# date, kind, circular, what it is, hours (open, close) or None, intervals, text that must be in the circular
ROWS = [
    ("2017-10-19", "MUHURAT", "CMTR35993", "Diwali Muhurat session", ("18:30", "19:30"), None, ["Thursday, October 19, 2017", "18:30 hrs", "19:30 hrs"]),
    ("2018-11-07", "MUHURAT", "CMTR39216", "Diwali Muhurat session", ("17:30", "18:30"), None, ["Wednesday, November 07, 2018", "17:30 hrs", "18:30 hrs"]),
    ("2019-10-27", "MUHURAT", "CMTR42483", "Diwali Muhurat session (revised timings)", ("18:15", "19:15"), None, ["Sunday, October 27, 2019", "18:15 hrs", "19:15 hrs"]),
    ("2020-02-01", "SPECIAL", "CMTR43290", "live trading session, Union Budget day", ("09:15", "15:30"), None, ["Saturday, February 01, 2020", "Normal Market open time", "09:15 hrs", "15:30 hrs"]),
    ("2020-11-14", "MUHURAT", "CMTR46230", "Diwali Muhurat session", ("18:15", "19:15"), None, ["Saturday, November 14, 2020", "18:15 hrs", "19:15 hrs"]),
    ("2021-11-04", "MUHURAT", "CMTR50050", "Diwali Muhurat session", ("18:15", "19:15"), None, ["Thursday, November 04, 2021", "18:15 hrs", "19:15 hrs"]),
    ("2022-10-24", "MUHURAT", "CMTR54023", "Diwali Muhurat session", ("18:15", "19:15"), None, ["Monday, October 24, 2022", "18:15 hrs", "19:15 hrs"]),
    ("2023-11-12", "MUHURAT", "CMTR59124", "Diwali Muhurat session", ("18:15", "19:15"), None, ["Sunday, November 12, 2023", "18:15 hrs", "19:15 hrs"]),
    ("2024-01-20", "SPECIAL", "MSD60340", "regular trading session on a Saturday (the planned DR-site drill, NSE/MSD/59999, was withdrawn)", ("09:15", "15:30"), None, ["January 20,2024", "regular market timings", "withdrawn"]),
    ("2024-03-02", "SPECIAL", "MSD60677", "special live session with intra-day switch to the DR site", None, [("09:15", "10:00"), ("11:30", "12:30")], ["Saturday, March 02, 2024", "10:00 hrs", "11:30 hrs", "12:30 hrs"]),
    ("2024-05-18", "SPECIAL", "MSD61893", "special live session with intra-day switch to the DR site", None, [("09:15", "10:00"), ("11:30", "12:30")], ["Saturday, May 18, 2024", "10:00 hrs", "11:30 hrs", "12:30 hrs"]),
    ("2025-02-01", "SPECIAL", "CMTR65729", "live trading session, Union Budget day", ("09:15", "15:30"), None, ["Saturday, February 01, 2025", "09:15 hrs", "15:30 hrs"]),
    ("2025-10-21", "MUHURAT", "CMTR70319", "Diwali Muhurat session", ("13:45", "14:45"), None, ["Tuesday, October 21, 2025", "13:45 hrs", "14:45 hrs"]),
    ("2026-02-01", "SPECIAL", "CMTR72349", "live trading session, Union Budget day", ("09:15", "15:30"), None, ["Sunday, February 01, 2026", "09:15 hrs", "15:30 hrs"]),
    ("2026-11-08", "MUHURAT", "CMTR76941", "Diwali Muhurat session: continuous trading opens 14:20; closes 15:30 (15:15 for closing-auction securities, then the auction)", ("14:20", "15:30"), None, ["Sunday, November 08, 2026", "14:20", "15:30"]),
]  # fmt: skip

ap = argparse.ArgumentParser()
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--file", type=Path, default=Path("config/exchange_sessions.json"))
a = ap.parse_args()
lake, doc = LocalLake(a.lake), json.loads(a.file.read_text())
by_date = {s["date"]: s for s in doc["sessions"]}
for day, kind, cid, what, hours, intervals, must in ROWS:
    url = f"https://nsearchives.nseindia.com/content/circulars/{cid}.pdf"
    d = date.fromisoformat(day)
    have = [
        m for m in lake.versions("nse", "session_circulars", d) if m.url == url
    ]  # a corrected circular is a new version
    if have:
        data = lake.get(have[-1])
    else:
        data = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90
        ).read()  # noqa: S310
        if data[:4] != b"%PDF":
            raise SystemExit(f"{cid}: not a PDF")
        have = [
            lake.put("nse", "session_circulars", d, data, url=url, fetched_at=datetime.now(UTC))
        ]
    text = re.sub(
        r"\s+",
        " ",
        subprocess.run(
            ["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, check=True
        ).stdout.decode(),
    )
    missing = [m for m in must if re.sub(r"\s+", " ", m) not in text]
    if missing:
        raise SystemExit(f"{day} {cid}: the circular does not contain {missing}; nothing written")
    ref = re.search(r"NSE/[A-Z]+/\d+", text)
    ref = ref.group(0) if ref else cid
    entry = by_date.get(day) or {"date": day, "weekday": d.strftime("%A")}
    entry.update(kind=kind, kind_status=f"CONFIRMED ({ref}: {what})")
    if hours:
        entry["hours"] = list(hours)
        entry.pop("intervals", None)  # a corrected circular replaces an earlier split
        entry["hours_status"] = f"VERIFIED ({ref}: normal market {hours[0]}-{hours[1]})"
    else:
        entry["hours"] = None
        entry["intervals"] = [list(i) for i in intervals or []]
        entry["hours_status"] = SPLIT.format(
            i=" and ".join(f"{x}-{y}" for x, y in intervals or []) + f" per {ref}"
        )
    entry["evidence"] = (
        f"{url} (NSE circular {ref}, kept untouched in the lake: nse/session_circulars/dt={day})"
    )
    entry["evidence_sha256"] = have[-1].checksum
    by_date[day] = entry
    print(f"{day} {kind:8} {ref:16} {'hours ' + '-'.join(hours) if hours else 'two intervals'}")
doc["sessions"] = sorted(by_date.values(), key=lambda s: s["date"])
a.file.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
