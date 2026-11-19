# ruff: noqa: E501
"""Download NSE's public daily security list (price band, series and surveillance remarks per stock per day) for the extreme-move fade study.

Source: https://nsearchives.nseindia.com/content/equities/sec_list_DDMMYYYY.csv  (columns: Symbol, Series, Security Name, Band, Remarks). It exists from 2020-01-02; earlier dates answer 404.
`Band` is the day's price band in percent ("2", "5", "10", "20", "No Band"); `Series` EQ / BE / BZ / SM / ST ...; `Remarks` carries GSM stages. Known before the open of that day.
Raw files are cached untouched under data/research/nse_sec_list/ (git-ignored) with a manifest of sha256 per file, so the study is reproducible from the cache. One request per trading day, polite pace, nothing about this project is sent.
usage: fetch_nse_sec_list.py [--db URL] [--from 2020-01-01] [--to 2023-12-31] [--pause 0.3]"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data/research/nse_sec_list"
URL = "https://nsearchives.nseindia.com/content/equities/sec_list_{d}.csv"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--from", dest="start", default="2020-01-01")
ap.add_argument("--to", dest="end", default="2023-12-31")
ap.add_argument("--pause", type=float, default=0.3)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
if a.end >= "2024-01-01":
    sys.exit(
        "error: dates from 2024 on are not fetched (the protected holdout window starts 2025-01-01; this study stops at 2023-12-31)"
    )

with psycopg.connect(a.db) as conn:
    days = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date d FROM bar_1d WHERE source='nse' AND series='EQ' AND (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s ORDER BY d",
            (a.start, a.end),
        )
    ]
CACHE.mkdir(parents=True, exist_ok=True)
manifest_path = CACHE / "manifest.json"
manifest: dict[str, dict] = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
got = missing = cached = 0
for d in days:
    key = d.isoformat()
    f = CACHE / f"sec_list_{key}.csv"
    if f.exists() or manifest.get(key, {}).get("http") == 404:
        cached += 1
        continue
    req = urllib.request.Request(
        URL.format(d=d.strftime("%d%m%Y")), headers={"User-Agent": UA, "Accept": "text/csv,*/*"}
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            f.write_bytes(body)
            manifest[key] = {
                "http": 200,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
            got += 1
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                manifest[key] = {"http": 404}
                missing += 1
                break
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    else:
        print(f"gave up on {key}")
    time.sleep(a.pause)
    if (got + missing) % 100 == 0:
        manifest_path.write_text(json.dumps(manifest, indent=0, sort_keys=True))
manifest_path.write_text(json.dumps(manifest, indent=0, sort_keys=True))
print(
    f"{len(days)} trading days: fetched {got}, already cached {cached}, not published (404) {missing}; cache {CACHE}"
)
