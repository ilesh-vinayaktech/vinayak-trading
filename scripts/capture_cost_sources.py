# ruff: noqa: E501
"""Fetch the official fee documents and store them UNTOUCHED in the versioned raw lake, with sha256.
Cost-schedule rates must cite one of these (url + sha256 + quote); nothing is hardcoded from memory.
usage: capture_cost_sources.py --lake data/lake"""

import argparse
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from algo.data.lake import LocalLake

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
ARCH = "https://nsearchives.nseindia.com/content/circulars"
NSE_STATIC = "https://www.nseindia.com/static/invest"
SOURCES = {
    "zerodha_charges": "https://zerodha.com/charges",
    "nse_stt_levies_page": f"{NSE_STATIC}/first-time-investor-sebi-turnover-fees-stt-other-levies",
    "nse_stamp_duty_page": f"{NSE_STATIC}/first-time-investor-stamp-duty-charges-taxes",
    "nse_FA73061": f"{ARCH}/FA73061.pdf",  # transaction charges, 27 Feb 2026, effective 1 Mar 2026
    "nse_FA56129": f"{ARCH}/FA56129.pdf",  # transaction charges, 24 Mar 2023, effective 1 Apr 2023
    "nse_FATAX73524": f"{ARCH}/FATAX73524.pdf",  # STT, 31 Mar 2026
    "nse_FATAX63809": f"{ARCH}/FATAX63809.pdf",  # STT, 9 Sep 2024
    "nse_FATAX56235": f"{ARCH}/FATAX56235.pdf",  # STT, 1 Apr 2023
    "nse_FATAX43604": f"{ARCH}/FATAX43604.pdf",  # STT, 19 Feb 2020
    "nse_FATAX41263": f"{ARCH}/FATAX41263.pdf",  # STT, 7 Jun 2019
    "nse_FATAX32385": f"{ARCH}/FATAX32385.pdf",  # STT, 16 May 2016
    "zerodha_bulletin_2023_04": "https://zerodha.com/marketintel/bulletin/347967/revision-in-transaction-charges-and-stt-from-1st-april-2023",
    "zerodha_bulletin_2024_04": "https://zerodha.com/marketintel/bulletin/373933/revision-in-nse-transaction-charges-from-april-1-2024",
    "zerodha_bulletin_2024_10": "https://zerodha.com/marketintel/bulletin/391488/revision-in-transactions-charges-from-1st-october-2024",
    "zerodha_zero_brokerage_2015": "https://zerodha.com/z-connect/trending/brokerage-edge",
    "nse_FA46730": f"{ARCH}/FA46730.pdf",  # cash-market transaction charges 3.25 -> 3.45 per lakh (member tariff), 18 Dec 2020, effective 1 Jan 2021
    "nse_FA45147": f"{ARCH}/FA45147.pdf",  # temporary concessional EQ-series charges, 27 Jul 2020, 1 Aug to 31 Oct 2020
    "nse_FA47844": f"{ARCH}/FA47844.pdf",  # the concession extended, 31 Mar 2021
    "nse_FA49796": f"{ARCH}/FA49796.pdf",  # the concession extended, 30 Sep 2021
    "nse_FA51855": f"{ARCH}/FA51855.pdf",  # the concession revised from 1 Apr 2022, 31 Mar 2022
    "sebi_gst_circular_2022_07_18": "https://www.sebi.gov.in/sebi_data/attachdocs/jul-2022/1658208863370.pdf",  # GST 18% on fees payable to SEBI from 18 Jul 2022
    "zerodha_support_dp_charges": "https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/what-do-dp-charges-mean",  # current DP charge, and the once-per-scrip-per-day rule with examples
    "zerodha_forum_dp_2016": "https://tradingqna.com/t/dp-charges-and-stt-charges/5637",  # Zerodha's founder on Zerodha's forum, Mar 2016: Rs 13.5 per scrip per day
    "zerodha_forum_dp_2017": "https://tradingqna.com/t/dp-charges-i-think-there-is-some-mistake-in-the-website-please-confirm-me/19962",  # Sep 2017: Rs 13.5 only on the day you sell
    "zerodha_forum_dp_2024": "https://tradingqna.com/t/cdsl-reduced-charges-will-zerodha-too/165314",  # May 2024: a Zerodha reply that from 1 Jun 2024 DP falls from Rs 13.5 to Rs 13
    "cdsl_dp_tariff_2024_10": "https://www.cdslindia.com/eservices/Downloads/CDSL-DP-Tariff-structure_Oct-2024.pdf",
}

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument(
    "--only",
    nargs="*",
    help="fetch just these names (the lake is versioned: refetching adds a version, it never overwrites)",
)
a = ap.parse_args()
lake, now = LocalLake(a.lake), datetime.now(UTC)
for name, url in SOURCES.items():
    if a.only and name not in a.only:
        continue
    req = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310
    with urllib.request.urlopen(req, timeout=40) as r:  # noqa: S310
        data = bytes(r.read())
    m = lake.put("costs", name, now.date(), data, url=url, fetched_at=now)
    print(f"{name:22} v{m.version} {m.size:>8} bytes sha256={m.checksum}")
    time.sleep(2)
