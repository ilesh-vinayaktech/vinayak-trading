# ruff: noqa: E501
"""Earlier editions of the NSE Indices methodology documents, from the Internet Archive's copies of the official URLs. Each distinct edition
is kept untouched in the lake (niftyindices / methodology_*) and its text on total return indices and dividends is hashed, so a change in
the total-return treatment between editions is visible. Writes docs/benchmark-evidence/methodology_history.json.
usage: capture_methodology_history.py [--lake data/lake] [--delay 3]"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

from algo.data.lake import LocalLake

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
SOURCES = {  # dataset -> official URL (as served by NSE Indices / NSE)
    "methodology_equity": ["www.niftyindices.com/Methodology/Method_NIFTY_Equity_Indices.pdf", "archives.nseindia.com/content/indices/Method_NIFTY_Equity_Indices.pdf"],
    "methodology_nifty50": ["niftyindices.com/Methodology/Method_Nifty_50.pdf", "nseindia.com/content/indices/Method_Nifty_50.pdf"],
}  # fmt: skip
ap = argparse.ArgumentParser()
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--delay", type=float, default=3.0)
ap.add_argument(
    "--out", type=Path, default=Path("docs/benchmark-evidence/methodology_history.json")
)
a = ap.parse_args()
lake = LocalLake(a.lake)


def get(url: str) -> bytes:
    time.sleep(a.delay)
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120
    ) as r:  # noqa: S310
        return bytes(r.read())


def tri_text(pdf: bytes) -> tuple[str, str]:
    """(date line, the normalized lines that speak of total returns or dividends)"""
    text = subprocess.run(
        ["pdftotext", "-layout", "-", "-"],
        input=pdf,
        capture_output=True,
        check=False,  # damaged archived copies give partial text
    ).stdout.decode(errors="replace")
    lines = [re.sub(r"\s+", " ", x).strip().lower() for x in text.splitlines()]
    issued = next(
        (
            x
            for x in lines
            if re.search(
                r"(january|february|march|april|may|june|july|august|september|october|november|december) 20\d\d",
                x,
            )
        ),
        "",
    )
    keep = [x for x in lines if ("total return" in x or "dividend" in x) and len(x) > 25]
    return issued[:60], "\n".join(keep)


out: dict[str, list[dict[str, object]]] = {}
for dataset, urls in SOURCES.items():
    seen: set[str] = set()
    rows: list[dict[str, object]] = []
    for u in urls:
        cdx = json.loads(
            get(
                f"http://web.archive.org/cdx/search/cdx?url={u}&output=json&fl=timestamp,digest&filter=statuscode:200&collapse=digest"
            )
        )
        for ts, digest in cdx[1:]:
            if digest in seen:
                continue
            seen.add(digest)
            day = date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
            url = f"https://web.archive.org/web/{ts}id_/https://{u}"
            have = [m for m in lake.versions("niftyindices", dataset, day) if m.url == url]
            if have:
                data = lake.get(have[-1])
            else:
                data = get(url)
                if data[:4] != b"%PDF":
                    print(f"{dataset} {day}: not a PDF, skipped", file=sys.stderr)
                    continue
                have = [
                    lake.put(
                        "niftyindices", dataset, day, data, url=url, fetched_at=datetime.now(UTC)
                    )
                ]
            issued, tri = tri_text(data)
            rows.append({"captured": str(day), "source_url": u, "archive_url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                         "issued_line": issued, "tri_dividend_lines": tri.count("\n") + 1 if tri else 0, "tri_dividend_text_sha256": hashlib.sha256(tri.encode()).hexdigest()})  # fmt: skip
            print(f"{dataset} {day} {issued!r} lines={rows[-1]['tri_dividend_lines']}", flush=True)
    rows.sort(key=lambda r: str(r["captured"]))
    for prev, cur in zip(rows, rows[1:], strict=False):
        cur["tri_text_changed_from_previous"] = (
            prev["tri_dividend_text_sha256"] != cur["tri_dividend_text_sha256"]
        )
    out[dataset] = rows
doc = {"what": "official methodology documents as archived by the Internet Archive (web.archive.org); the text on total return indices and dividends is hashed per edition",
       "limit": "the Archive's copies start in 2018 (Nifty 50) and 2020 (all equity indices); earlier editions could not be retrieved", "editions": out}  # fmt: skip
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(doc, indent=1) + "\n")
print({k: len(v) for k, v in out.items()})
