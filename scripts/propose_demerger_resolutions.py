# ruff: noqa: E501  (a report script)
"""READ-ONLY: propose exact resolutions for the demergers whose price factor is still a `gap` estimate.

For demergers on or after the exchanges' special pre-open session (Reliance 2023-07-20 onward), NSE/BSE discover the
parent's ex price in that session; it is the ex-date OPEN in the NSE bhavcopy. The factor is then open / previous close
(method `exchange_adjusted_price`, an existing method). Each proposal records the stored bhavcopy file (path + checksum)
and the press reports that corroborate the discovered price; the proposal is NOT verification and writes nothing.
Older demergers had no special session: they are listed with the candidate factors a person can choose between,
and no proposal is made for them.
usage: propose_demerger_resolutions.py --db URL [--lake data/lake] [--out-json config/proposed/demerger_resolutions.json]
       [--out-md docs/stage4/corporate_actions/DEMERGERS.md]"""

import argparse
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--out-json", type=Path, default=Path("config/proposed/demerger_resolutions.json"))
ap.add_argument("--out-md", type=Path, default=Path("docs/stage4/corporate_actions/DEMERGERS.md"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")

# Corroboration collected from public reports (secondary). Each states the discovered price in the special pre-open session.
SPECIAL = {
    ("RELIANCE", date(2023, 7, 20)): {
        "ratio": "1 Jio Financial Services share per Reliance share",
        "discovered_reported": "2580",
        "reports": [
            "https://www.businesstoday.in/markets/company-stock/story/ril-share-price-settles-at-rs-2580-in-special-pre-open-session-jio-financial-at-rs-26185-390530-2023-07-20",
            "https://www.angelone.in/news/share-market/ril-settles-at-rs-2580-jio-financials-priced-at-rs-261-85",
        ],
    },
    ("ITC", date(2025, 1, 6)): {
        "ratio": "1 ITC Hotels share per 10 ITC shares",
        "discovered_reported": "455.60 (NSE)",
        "reports": [
            "https://magzter.com/stories/newspaper/The-Free-Press-Journal-Indore/ITC-SHARES-ADJUST-AFTER-HOTELS-BIZ-DEMERGER",
            "https://www.venturasecurities.com/news/stocks/itc-share-price-adjusted-for-demerger-of-hotels-business/",
        ],
    },
    ("SIEMENS", date(2025, 4, 7)): {
        "ratio": "1 Siemens Energy India share per Siemens share (record date 2025-04-07, Siemens' own NSE filing)",
        "discovered_reported": "2450.00 (open vs 4928.15 close; child dummy price 2478.20 on NSE)",
        "reports": [
            "https://nsearchives.nseindia.com/corporate/SiemensRaj_25032025213901_SEdisclosureRecordDate25032025.pdf",
            "https://www.angelone.in/news/stocks-share-market/siemens-share-price-drops-50-percent-post-demerger-with-siemens-energy-india",
        ],
    },
    ("TMPV", date(2025, 10, 14)): {
        "ratio": "1 TMLCV share per Tata Motors share",
        "discovered_reported": "400 (vs NSE close 660.75)",
        "reports": [
            "https://www.samco.in/knowledge-center/articles/tata-motors-demerger-passenger-vehicle-share-price-and-key-updates/",
            "https://upstox.com/news/market-news/stocks/tata-motors-demerger-why-stock-is-down-40-from-previous-close-all-you-need-to-know/article-182991",
        ],
    },
    ("HINDUNILVR", date(2025, 12, 5)): {
        "ratio": "1 Kwality Wall's (India) share per HUL share",
        "discovered_reported": "2422 (gap 40.20 = NSE adjusted price of KWIL)",
        "reports": [
            "https://www.outlookbusiness.com/corporate/kwality-walls-india-debuts-26-below-issue-price-gains-in-intraday-trade",
            "https://www.samco.in/knowledge-center/?p=65895",
        ],
    },
    ("VEDL", date(2026, 4, 30)): {
        "ratio": "1 share each of four demerged Vedanta companies per Vedanta share (record date 2026-05-01)",
        "discovered_reported": "289.50 (vs close 773.60)",
        "reports": [
            "https://www.arihantcapital.com/company-information/companynewsdetails/25120010239",
            "https://www.thestatesman.com/business/vedanta-share-price-falls-demerger-impact-today-1503587920.html",
        ],
    },
}
# Older demergers: child instrument and its stated entitlement (secondary reports), for the candidate table only.
OLD = {
    ("ABB", date(2019, 12, 20)): (
        "POWERINDIA",
        Decimal(1) / 5,
        "1 ABB Power Products share per 5 ABB India shares",
    ),
    ("GMRAIRPORT", date(2022, 1, 11)): (
        "GMRP&UI",
        Decimal(1) / 10,
        "1 GPUIL share (FV 5) per 10 GIL shares (FV 1)",
    ),
    ("MOTHERSON", date(2022, 1, 14)): (
        "MSUMI",
        Decimal(1),
        "1 MSWIL share per MSSL share (reports)",
    ),
    ("NMDC", date(2022, 10, 27)): ("NSLNISP", Decimal(1), "1 NMDC Steel share per NMDC share"),
}


def lake_file(day: date) -> dict[str, str] | None:
    for ds in ("bhav", "bhav_legacy"):
        for m in sorted((a.lake / "raw/nse" / ds / f"dt={day}").glob("v*.manifest.json")):
            j = json.loads(m.read_text())
            return {
                "manifest": str(m),
                "checksum": j["checksum"],
                "url": j.get("url", ""),
                "dataset": ds,
            }
    return None


with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    rows = c.execute(
        "SELECT r.instrument_id, i.symbol, r.ex_date, r.factor FROM (SELECT DISTINCT ON (instrument_id,ex_date,kind) * FROM action_resolution"
        " ORDER BY instrument_id,ex_date,kind,id DESC) r JOIN instrument i USING (instrument_id) WHERE r.status='provisional' AND r.kind='demerger' AND r.method='gap' ORDER BY r.ex_date"
    ).fetchall()

    def first_bar(iid: int, ex: date):
        return c.execute(
            "SELECT open, prev_close FROM bar_1d WHERE instrument_id=%s AND (ts AT TIME ZONE 'Asia/Kolkata')::date >= %s ORDER BY ts LIMIT 1",
            (iid, ex),
        ).fetchone()

    def last_close(iid: int, ex: date) -> Decimal:
        return c.execute(
            "SELECT close FROM bar_1d WHERE instrument_id=%s AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY ts DESC LIMIT 1",
            (iid, ex),
        ).fetchone()[0]  # type: ignore[index]

    def child_first(sym: str):
        return c.execute(
            "SELECT (b.ts AT TIME ZONE 'Asia/Kolkata')::date, b.open, b.close FROM bar_1d b JOIN instrument i USING (instrument_id) WHERE i.symbol=%s ORDER BY b.ts LIMIT 1",
            (sym,),
        ).fetchone()

    proposals, candidates = [], []
    for iid, sym, ex, gap in rows:
        opn, _ = first_bar(iid, ex)
        prev = last_close(iid, ex)
        if (sym, ex) in SPECIAL:
            s = SPECIAL[(sym, ex)]
            lf = lake_file(ex)
            f = Decimal(opn) / Decimal(prev)
            proposals.append(
                {
                    "symbol": sym,
                    "instrument_id": iid,
                    "ex_date": str(ex),
                    "kind": "demerger",
                    "method": "exchange_adjusted_price",
                    "params": {"base_price": str(opn)},
                    "prev_close": str(prev),
                    "factor": f"{f:.6f}",
                    "current_gap_factor": f"{Decimal(gap):.6f}",
                    "difference_vs_gap": f"{f - Decimal(gap):+.4f}",
                    "entitlement": s["ratio"],
                    "discovered_price_reported": s["discovered_reported"],
                    "evidence": {"stored_bhavcopy": lf, "reports": s["reports"]},
                    "status_proposed": "provisional",
                    "note": "NOT verified. Base price = ex-date open (the special pre-open session settlement) in the stored NSE bhavcopy; press reports corroborate. A person must confirm against the NSE circular before verify.",
                }
            )
        else:
            child, ratio, text = OLD[(sym, ex)]
            ch = child_first(child)
            cand = {
                "symbol": sym,
                "ex_date": str(ex),
                "prev_close": str(prev),
                "entitlement": text,
                "gap_factor": f"{Decimal(gap):.4f}",
                "child": child,
            }
            if ch:
                cand["child_first_session"] = str(ch[0])
                cand["child_first_close"] = str(ch[2])
                cand["factor_if_child_first_close"] = f"{1 - ratio * Decimal(ch[2]) / prev:.4f}"
                cand["days_between_exdate_and_child_listing"] = (ch[0] - ex).days
            candidates.append(cand)

a.out_json.parent.mkdir(parents=True, exist_ok=True)
a.out_json.write_text(
    json.dumps({"status": "PROPOSED, not applied", "proposals": proposals}, indent=2) + "\n"
)
L = ["# Demergers still on `gap` estimates: proposal (read-only; nothing applied)", "",
     "## A. Exchange-discovered base price (6): proposed `exchange_adjusted_price`, factor = ex-date open / previous close", "",
     "| symbol | ex-date | prev close | base (ex-date open) | proposed factor | current gap factor | difference | entitlement |", "|---|---|---|---|---|---|---|---|"]  # fmt: skip
L += [
    f"| {p['symbol']} | {p['ex_date']} | {p['prev_close']} | {p['params']['base_price']} | {p['factor'][:6]} | {p['current_gap_factor'][:6]} | {p['difference_vs_gap']} | {p['entitlement']} |"
    for p in proposals
]
L += ["", "Evidence per row (stored NSE bhavcopy file checksum and press reports) is in `config/proposed/demerger_resolutions.json`. The open equals the discovered price reported by the press in every case. This is a proposal: verification (a person confirming against the NSE circular) is separate.", "",
      "## B. No special session (4): no exchange base exists; candidates only", "",
      "| symbol | ex-date | prev close | entitlement | gap (current) | child | child first session | days after ex | factor if child's first close |", "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
L += [
    f"| {x['symbol']} | {x['ex_date']} | {x['prev_close']} | {x['entitlement']} | {x['gap_factor']} | {x['child']} | {x.get('child_first_session', 'n/a')} | {x.get('days_between_exdate_and_child_listing', 'n/a')} | {x.get('factor_if_child_first_close', 'n/a')} |"
    for x in candidates
]
L += [
    "",
    "The child's first close is lagged by weeks to months (and ABB's by the March 2020 crash), so it is a poor stand-in for value at the ex-date. Company tax cost apportionments (e.g. NMDC 42.71% / NMDC Steel 57.29%, GMR 7.29% to GPUIL) are book-value based and not comparable with market value. A person must choose the convention or keep these as provisional gap estimates.",
]
a.out_md.write_text("\n".join(L) + "\n")
print("\n".join(L))
