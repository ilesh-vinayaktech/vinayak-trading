# ruff: noqa: E501  (a report script)
"""READ-ONLY: propose TERP resolutions for the rights issues that affect the research window.

factor = TERP / P with TERP = (B*P + A*S) / (A + B): B shares held, A new shares, S the FULL issue price, P the
previous cum-rights close from the database (= the NSE bhavcopy close). This is the existing `rights` method and is
algebraically the exchanges' F&O rights adjustment factor (P - E) / P. Where an exchange-published factor was found,
the report shows whether ours reproduces it. No exchange adjusts the cash-market base price for a rights issue, so
there is no exchange base price to take precedence. Nothing is written.
usage: propose_rights_resolutions.py --db URL [--out-json config/proposed/rights_resolutions.json]
       [--out-md docs/stage4/corporate_actions/RIGHTS.md]"""

import argparse
import json
import os
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import psycopg

from algo.data.adjust.factors import rights_factor

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out-json", type=Path, default=Path("config/proposed/rights_resolutions.json"))
ap.add_argument("--out-md", type=Path, default=Path("docs/stage4/corporate_actions/RIGHTS.md"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")

# Terms as found in public sources (letters of offer are linked; most are not yet retrieved and read).
# (symbol, ex_date, A new, B held, face value, premium, payment structure, exchange factor found or None, sources)
TERMS = [
    (
        "RELIANCE",
        "2020-05-13",
        1,
        15,
        "10",
        "1247",
        "PARTLY PAID: Rs 314.25 on application (25%), balance in two calls; the partly paid shares listed separately",
        None,
        [
            "https://archives.nseindia.com/content/circulars/CML44626.pdf (NSE listing circular, not retrieved)",
            "https://business.bofa.com/content/dam/flagship/in/en/investment-banking/Reliance-Industries-Limited-Letter-of-Offer.pdf (letter of offer, not retrieved)",
            "https://zerodha.com/marketintel/bulletin/254966/adjustment-of-futures-and-options-contracts-of-reliance (F&O adjustment, revised lot 505)",
        ],
    ),
    (
        "SHRIRAMFIN",
        "2020-07-09",
        3,
        26,
        "10",
        "560",
        "fully paid (Shriram Transport Finance)",
        None,
        [
            "https://www.sebi.gov.in/filings/rights-issues/jul-2020/shriram-transport-finance-company-limited_47033.html (letter of offer, not retrieved)",
            "NSE F&O circular 096/2020 (methodology NSE/FAOP/44945), factor not retrieved",
        ],
    ),
    (
        "LTF",
        "2021-01-21",
        17,
        74,
        "10",
        "55",
        "fully paid (L&T Finance Holdings)",
        None,
        [
            "https://www.msei.in/SX-Content/Circulars/2021/January/Circular-10020.pdf (MSE circular, cum close 103.85, revised lot 8924; factor not read)"
        ],
    ),
    (
        "BHARTIARTL",
        "2021-09-27",
        1,
        14,
        "5",
        "530",
        "PARTLY PAID: Rs 133.75 on application (25%), balance in calls; the partly paid shares listed separately",
        "0.981571",
        [
            "https://www.msei.in/SX-Content/Circulars/2021/September/Circular-10921.pdf (MSE circular: AF = (P-E)/P = 0.981571)",
            "https://assets.airtel.in/teams/simplycms/web/docs/Letter_of_Offer_dated_September_22-2021.pdf (letter of offer, not retrieved)",
        ],
    ),
    (
        "INDHOTEL",
        "2021-11-11",
        1,
        9,
        "1",
        "149",
        "fully paid",
        None,
        [
            "https://investmentbank.kotak.com/downloads/the-indian-hotels-company-limited-abridged-letter-of-offer.pdf (abridged letter of offer, not retrieved)",
            "NSE F&O circular Annexure-1 (revised lot 4022), factor not retrieved",
        ],
    ),
    (
        "SUZLON",
        "2022-10-03",
        5,
        21,
        "2",
        "3",
        "PARTLY PAID (Re 1 paid on application per a later BSE filing; first and final call Rs 2.50 per the call notice); not an F&O stock then; issue proceeded and closed 1.8x subscribed",
        None,
        [
            "https://pv-magazine-india.com/press-releases/suzlon-energy-inr-1200-crore-rights-issue-to-open-on-october-11-2022",
            "letter of offer not located",
        ],
    ),
    (
        "GRASIM",
        "2024-01-10",
        6,
        179,
        "2",
        "1810",
        "PARTLY PAID: Rs 453 on application, balance Rs 1,359 in calls",
        "0.996040",
        [
            "https://zerodha.com/marketintel/bulletin/368337/adjustment-of-futures-and-options-contracts-of-grasim-due-to-rights-issue (factor 0.996040)",
            "https://business.bofa.com/content/dam/flagship/in/en/investment-banking/Grasim-Industries-Limited-Abridged-Letter-of-Offer.pdf (abridged letter of offer, not retrieved)",
        ],
    ),
    (
        "TATACONSUM",
        "2024-07-26",
        1,
        26,
        "1",
        "817",
        "terms say Rs 818 per share; payment structure not confirmed; the exchange worked example used a cum close of 1231.25, which differs from the 25 Jul close 1223.60 in the bhavcopy",
        None,
        [
            "https://zerodha.com/marketintel/bulletin/384895/adjustment-of-futures-and-options-contracts-of-tataconsum-due-to-rights-issue",
            "https://investmentbank.kotak.com/downloads/tataconsumer-abridged-letter-of-offer.pdf (abridged letter of offer, not retrieved)",
        ],
    ),
    (
        "UPL",
        "2024-11-26",
        1,
        8,
        "2",
        "358",
        "PARTLY PAID: Rs 90 on application, balance in calls",
        "0.959243",
        [
            "https://nsearchives.nseindia.com/content/circulars/FAOP65222.pdf (NSE: indicative AF 0.959243 at cum close 568.55)",
            "NSE circular 149/2024 reported AF 0.959510 (implies a different P; not retrieved)",
        ],
    ),
    (
        "ADANIENT",
        "2025-11-17",
        3,
        25,
        "1",
        "1799",
        "PARTLY PAID: Rs 900 on application, balance in two calls (record dates 2025-12-23 and 2026-02-13)",
        "0.969485",
        [
            "https://tradingqna.com/t/adjustments-in-f-o-contracts-of-adani-enterprises-limited-adanient-on-account-of-rights-issue-2025/188697 (forum copy of the exchange notice: AF 0.969485)",
            "https://www.adanienterprises.com/-/media/Project/Enterprises/Investors/Investor-Downloads/Rights-Issue-Other-Documents/FAQs_Partly-paid-equity-shares_Rights-Issue.pdf",
        ],
    ),
]

with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    rows = []
    for sym, ex, A, B, fv, prem, pay, exch, src in TERMS:
        exd = date.fromisoformat(ex)
        iid = c.execute("SELECT instrument_id FROM instrument WHERE symbol=%s", (sym,)).fetchone()[
            0
        ]  # type: ignore[index]
        rec = c.execute(
            "SELECT subject, record_date FROM corporate_action WHERE instrument_id=%s AND ex_date=%s AND kind='rights'",
            (iid, exd),
        ).fetchone()
        prev = c.execute(
            "SELECT close FROM bar_1d WHERE instrument_id=%s AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY ts DESC LIMIT 1",
            (iid, exd),
        ).fetchone()[0]  # type: ignore[index]
        S = D(fv) + D(prem)
        f = rights_factor(D(A), D(B), S, prev)
        rows.append({
            "symbol": sym, "instrument_id": iid, "ex_date": ex, "record_date": str(rec[1]) if rec else None, "subject": rec[0] if rec else None,
            "method": "rights", "params": {"new": str(A), "held": str(B), "subscription_price": str(S)}, "prev_close": str(prev),
            "factor": str(f), "face_value": fv, "premium": prem, "payment": pay,
            "exchange_factor_found": exch, "reproduces_exchange_factor": (f"{f:.6f}" == exch) if exch else None,
            "sources": src, "status_proposed": "provisional",
            "evidence_class_when_recorded": "PROVISIONAL_FROM_TERMS",
            "limitation": "terms from public reports and exchange-notice copies; the letter of offer has not been retrieved and read. NOT verified.",
        })  # fmt: skip

a.out_json.parent.mkdir(parents=True, exist_ok=True)
a.out_json.write_text(
    json.dumps(
        {
            "status": "PROPOSED, not applied",
            "formula": "factor = (B*P + A*S) / ((A+B) * P), S = full issue price",
            "proposals": rows,
        },
        indent=2,
    )
    + "\n"
)
L = ["# Rights issues affecting the research window: TERP proposal (read-only; nothing applied)", "",
     "factor = TERP / P, TERP = (B x P + A x S) / (A + B), S = the FULL issue price (face value + premium), P = previous cum-rights close.",
     "This equals the exchanges' F&O rights adjustment factor (P - E) / P. No exchange adjusts the cash-market base price for a rights issue",
     "(the bhavcopy PREV_CLOSE on every ex-date is the unadjusted cum close), so there is no exchange base price to take precedence.", "",
     "| symbol | ex-date | A:B | issue price | P (cum close) | proposed factor | exchange factor found | reproduced | payment |", "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
for r in rows:
    rep = (
        "n/a"
        if r["reproduces_exchange_factor"] is None
        else ("yes" if r["reproduces_exchange_factor"] else "NO")
    )
    L.append(
        f"| {r['symbol']} | {r['ex_date']} | {r['params']['new']}:{r['params']['held']} | {r['params']['subscription_price']} | {r['prev_close']} | {D(r['factor']):.6f} | {r['exchange_factor_found'] or '-'} | {rep} | {r['payment']} |"
    )
L += [
    "",
    "Sources per row (and which were not retrieved) are in `config/proposed/rights_resolutions.json`.",
]
a.out_md.write_text("\n".join(L) + "\n")
print("\n".join(L))
