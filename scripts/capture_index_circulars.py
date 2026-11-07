"""Store the NSE Indices press-release index and every index-change press release (from --since)
UNTOUCHED in the versioned raw lake, with sha256. Resumable (skips documents already stored),
sequential with a delay, and it STOPS on the first refusal (403/429/5xx) instead of retrying.
usage: capture_index_circulars.py --lake data/lake [--since 2015-01-01] [--delay 2.5]
       [--also ind_prs23032020 ...]   (explicit releases the title filter would skip)"""

import argparse
import html
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

from algo.data.lake import LocalLake

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
BASE = "https://www.niftyindices.com"
INCLUDE = re.compile(r"change|replace|exclu|inclu|reconstitut|review|criteria|adjust", re.I)
EXCLUDE = re.compile(
    r"SME|Emerge|FPI|ESG|IPO|Waves|fixed income|G-Sec|bond|SDL|liquid|volatil|strategy|factor|"
    r"crypto|Gold|Quality|Momentum|Alpha|Low Vol|Value|Dividend|Equal|Bank index|Pharma|IT index|"
    r"Midcap Select|Realty|sector|thematic|REITs|InvIT",
    re.I,
)  # ponytail: title filter, may miss odd titles; coverage is declared only after a person checks


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return bytes(r.read())


def parse_index(page: str) -> list[tuple[date, str, str]]:
    items = re.findall(
        r'data-date="([^"]+)".*?href=\'(/Press_Release/[^\']+)\'[^>]*>([^<]*)</a>', page, flags=re.S
    )
    return [
        (datetime.strptime(d, "%b %d, %Y").replace(tzinfo=UTC).date(), p, html.unescape(t).strip())
        for d, p, t in items
    ]


def candidates(items: list[tuple[date, str, str]], since: date) -> list[tuple[date, str, str]]:
    seen: set[str] = set()
    out = []
    for d, p, t in items:
        if d >= since and p not in seen and INCLUDE.search(t) and not EXCLUDE.search(t):
            seen.add(p)
            out.append((d, p, t))
    return sorted(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", required=True, type=Path)
    ap.add_argument("--since", default="2015-01-01")
    ap.add_argument("--delay", type=float, default=2.5)
    ap.add_argument("--also", action="append", default=[], help="press-release file stem to add")
    a = ap.parse_args()
    lake, now = LocalLake(a.lake), datetime.now(UTC)
    page_bytes = fetch(f"{BASE}/press-release")
    m = lake.put("niftyindices", "press_release_index", now.date(), page_bytes,
                 url=f"{BASE}/press-release", fetched_at=now)  # fmt: skip
    print(f"index page v{m.version} sha256={m.checksum}")
    listed = parse_index(page_bytes.decode("utf-8", "replace"))
    todo = candidates(listed, date.fromisoformat(a.since))
    wanted = {f"/Press_Release/{x}.pdf" for x in a.also}
    extra = [row for row in listed if row[1] in wanted and row not in todo]
    if {r[1] for r in extra} | {r[1] for r in todo} < wanted:
        sys.exit(f"--also names not in the press-release index: {sorted(wanted)}")
    todo = sorted(todo + extra)
    print(f"{len(todo)} candidate documents since {a.since}")
    got = skipped = 0
    for d, path, title in todo:
        ds = "pr_" + Path(path).stem
        if lake.versions("niftyindices", ds, d):
            skipped += 1
            continue
        time.sleep(a.delay)
        try:
            data = fetch(BASE + path)
        except urllib.error.HTTPError as e:
            sys.exit(
                f"STOPPED at {path}: HTTP {e.code} (not retrying). stored {got}, skipped {skipped}"
            )
        if not data.startswith(b"%PDF"):
            sys.exit(f"STOPPED at {path}: not a PDF ({len(data)} bytes)")
        lake.put("niftyindices", ds, d, data, url=BASE + path, fetched_at=datetime.now(UTC))
        got += 1
        print(f"{d} {path} {len(data):>8} bytes  {title[:60]}")
    print(f"done: stored {got}, already present {skipped}")
