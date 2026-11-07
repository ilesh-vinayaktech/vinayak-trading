"""Build config/cost_schedules/*.json from the official documents captured in the raw lake.
Every rate cites a source: url + sha256 of the stored document + a literal quote that this script
checks is really present in that document. Nothing is typed in from memory: change a rate by
changing the cited document, then re-run. Status is `extracted_unverified` until a PERSON verifies
(edit verified_by / verified_at after checking each quote against its document).
usage: build_cost_schedules.py --lake data/lake"""

import argparse
import html
import json
import re
import subprocess
import tempfile
from pathlib import Path

from algo.data.lake import LocalLake

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--out", type=Path, default=Path("config/cost_schedules"))
a = ap.parse_args()
lake = LocalLake(a.lake)


def doc(name: str) -> tuple[str, dict[str, str], str]:
    m = lake.latest("costs", name)
    assert m is not None, f"{name} not captured: run capture_cost_sources.py"
    data = lake.get(m)
    if data[:4] == b"%PDF":
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(data)
            f.flush()
            text = subprocess.run(
                ["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, check=True
            ).stdout
    else:
        t = re.sub(r"(?is)<(script|style).*?</\1>", "", data.decode("utf-8", "replace"))
        text = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return (
        " ".join(text.split()),
        {"url": m.url, "retrieved_at": m.fetched_at, "sha256": m.checksum},
        name,
    )


SRC: dict[str, dict[str, str]] = {}


def src(key: str, document: str, quote: str, locator: str) -> str:
    text, meta, _ = doc(document)
    needle = " ".join(quote.split())
    assert needle in text, f"quote not found in {document}: {quote!r}"
    SRC[key] = {**meta, "quote": quote, "locator": locator}
    return key


Z, NSE = "zerodha_charges", "nse_"
s_brk_del = src(
    "zerodha_brokerage_delivery",
    Z,
    "All equity delivery investments (NSE, BSE), are absolutely free — ₹ 0 brokerage.",
    "Charges > Free equity delivery",
)
s_brk_id = src(
    "zerodha_brokerage_intraday",
    Z,
    "0.03% or Rs. 20/executed order whichever is lower",
    "Equity table > Brokerage > Equity intraday",
)
s_stt_del = src(
    "zerodha_stt_delivery", Z, "0.1% on buy & sell", "Equity table > STT/CTT > Equity delivery"
)
s_stt_id = src(
    "zerodha_stt_intraday", Z, "0.025% on the sell side", "Equity table > STT/CTT > Equity intraday"
)
s_txn = src(
    "zerodha_nse_transaction",
    Z,
    "NSE: 0.00307%",
    "Equity table > Transaction charges (NSE), delivery and intraday",
)
s_gst = src(
    "zerodha_gst",
    Z,
    "18% of ( brokerage + SEBI charges + transaction charges)",
    "Other charges > GST",
)
s_sebi = src(
    "zerodha_sebi",
    Z,
    "Charged at ₹10 per crore + GST by Securities and Exchange Board of India",
    "Other charges > SEBI Charges",
)
s_sebi_note = src(
    "zerodha_sebi_pending_note",
    Z,
    "*SEBI charges will be reduced to ₹15 per crore once the regulator announces a date.",
    "Equity table footnote (recorded verbatim; wording unexplained, not applied)",
)
s_stamp_del = src(
    "zerodha_stamp_delivery",
    Z,
    "0.015% or ₹1500 / crore on buy side",
    "Equity table > Stamp charges > Equity delivery",
)
s_stamp_id = src(
    "zerodha_stamp_intraday",
    Z,
    "0.003% or ₹300 / crore on buy side",
    "Equity table > Stamp charges > Equity intraday",
)
s_dp = src(
    "zerodha_dp_charge",
    Z,
    "₹15.34 per scrip (₹3.5 CDSL fee + ₹9.5 Zerodha fee + ₹2.34 GST) is charged on the trading account ledger when stocks are sold, irrespective of quantity.",
    "Other charges > DP charges",
)
s_min = src(
    "zerodha_contract_note_minimum",
    Z,
    "For Delivery based trades, a minimum of ₹0.01 will be charged per contract note.",
    "Disclaimer",
)
s_ipft = src(
    "zerodha_ipft",
    Z,
    "Equity and Futures - ₹0.01 per crore + GST of the traded value.",
    "Other charges > IPFT (not modelled separately: NSE's 0.00307% total already includes its 0.01/crore contribution)",
)
s_nse_txn = src(
    "nse_FA73061_cash_market",
    "nse_FA73061",
    "Cash Market Rs. 297 Rs. 10 each Rs. 307 each Rs. 306.99 Rs. 0.01 each Rs. 307 each",
    "Table: existing vs revised outflow, Cash Market row (total unchanged at Rs 307 per crore per side)",
)
s_nse_txn_dt = src(
    "nse_FA73061_effective",
    "nse_FA73061",
    "The above revision will be applicable with effect from March 1, 2026.",
    "Circular NSE/FA/73061 dated 27 Feb 2026",
)
s_stt_nse = src(
    "nse_FATAX73524_delivery",
    "nse_FATAX73524",
    "Purchase of an equity share in a company or a unit 0.1 per cent 0.1 per cent Purchaser",
    "Table row 1 (delivery buy 0.1%, purchaser; unchanged)",
)
s_stt_nse_id = src(
    "nse_FATAX73524_intraday",
    "nse_FATAX73524",
    "Sale of an equity share in a company or a unit of 0.025 per cent 0.025 per cent Seller",
    "Table row 3 (settled otherwise than by delivery: 0.025%, seller; unchanged)",
)
s_stt_2024 = src(
    "nse_FATAX63809_cash_unchanged",
    "nse_FATAX63809",
    "Sale of an equity share in a 0.1 per cent 0.1 per cent Seller",
    "Circular NSE/FATAX/63809, 9 Sep 2024: delivery sell 0.1%, (No Change)",
)
s_stt_2023 = src(
    "nse_FATAX56235_cash_unchanged",
    "nse_FATAX56235",
    "Sale of an equity share in a 0.1 per cent 0.1 per cent Seller",
    "Circular NSE/FATAX/56235, 1 Apr 2023: delivery sell 0.1%, (No Change)",
)
s_stt_2016 = src(
    "nse_FATAX32385_cash_unchanged",
    "nse_FATAX32385",
    "Sale of an equity share in a 0.1 per cent 0.1 per cent Seller",
    "Circular NSE/FATAX/32385, 16 May 2016 (effective 1 Jun 2016): delivery sell 0.1%, (No Change)",
)
s_stamp_nse = src(
    "nse_stamp_duty",
    "nse_stamp_duty_page",
    "Transfer of Security other than debenture on delivery basis 0.015% Buyer Transfer of Security other than debenture on non-delivery basis 0.003% Buyer",
    "Stamp Duty table",
)
s_stamp_dt = src(
    "nse_stamp_duty_effective",
    "nse_stamp_duty_page",
    "with effect from July 1, 2020, being the notified date, stamp duty is levied and collected by Clearing Corporations",
    "Stamp Duty note",
)
s_sebi_nse = src(
    "nse_sebi_turnover_fee",
    "nse_stt_levies_page",
    "All sale and purchase transactions in securities other than debt securities 0.0001 per cent of the price at which the securities are purchased or sold (Rs.10 per crore)",
    "SEBI Turnover fees table (page undated)",
)
s_gst_nse = src(
    "nse_gst",
    "nse_stt_levies_page",
    "Stock brokers Services 18.00% (GST) Brokers and collected from their clients.",
    "GST table (page undated)",
)
s_txn_slab = src(
    "nse_FA56129_member_slabs",
    "nse_FA56129",
    "Up to 1250 Crores Rs 3.45 each side Rs 3.25 each side",
    "Cash Market slab table: a MEMBER tariff by monthly turnover - not a client rate",
)


def comp(
    type_,
    basis,
    side,
    *,
    rate=None,
    amount=None,
    minimum=None,
    maximum=None,
    gst=False,
    incl=False,
    source,
):
    d = {"type": type_, "basis": basis, "side": side, "taxable_for_gst": gst, "gst_inclusive": incl,
         "rounding": "HALF_UP_2DP", "source": source}  # fmt: skip
    for k, v in (
        ("rate_pct", rate),
        ("amount", amount),
        ("minimum", minimum),
        ("maximum", maximum),
    ):
        if v is not None:
            d[k] = v
    return d


def components(product: str) -> list[dict]:
    if product == "DELIVERY":
        return [
            comp("BROKERAGE", "TRADE_VALUE", "BOTH", rate="0", gst=True, source=s_brk_del),
            comp("STT", "TRADE_VALUE", "BOTH", rate="0.1", source=s_stt_del),
            comp(
                "EXCHANGE_TRANSACTION",
                "TRADE_VALUE",
                "BOTH",
                rate="0.00307",
                gst=True,
                source=s_txn,
            ),
            comp("SEBI_TURNOVER", "TRADE_VALUE", "BOTH", rate="0.0001", gst=True, source=s_sebi),
            comp("STAMP_DUTY", "TRADE_VALUE", "BUY", rate="0.015", source=s_stamp_del),
            comp("DP_CHARGE", "PER_SCRIP", "SELL", amount="15.34", incl=True, source=s_dp),
            comp("GST", "GST_BASE", "BOTH", rate="18", source=s_gst),
        ]
    return [
        comp(
            "BROKERAGE", "TRADE_VALUE", "BOTH", rate="0.03", maximum="20", gst=True, source=s_brk_id
        ),
        comp("STT", "TRADE_VALUE", "SELL", rate="0.025", source=s_stt_id),
        comp("EXCHANGE_TRANSACTION", "TRADE_VALUE", "BOTH", rate="0.00307", gst=True, source=s_txn),
        comp("SEBI_TURNOVER", "TRADE_VALUE", "BOTH", rate="0.0001", gst=True, source=s_sebi),
        comp("STAMP_DUTY", "TRADE_VALUE", "BUY", rate="0.003", source=s_stamp_id),
        comp("GST", "GST_BASE", "BOTH", rate="18", source=s_gst),
    ]


def schedule(product, *, id_, valid_from, valid_until, status, notes, keys):
    return {
        "id": id_, "version": "2026-11-07.1", "name": f"NSE cash equity {product.lower()} via Zerodha",
        "broker": "zerodha", "exchange": "NSE", "segment": "CASH", "instrument_type": "EQUITY",
        "product": product, "valid_from": valid_from, "valid_until": valid_until, "currency": "INR",
        "status": status, "verified_by": None, "verified_at": None, "notes": notes,
        "contract_note_min_brokerage": "0.01" if product == "DELIVERY" else None,
        "components": components(product), "sources": {k: SRC[k] for k in keys},
    }  # fmt: skip


def used(product):
    return sorted({c["source"] for c in components(product)})


CURRENT_NOTES = (
    "Rates read from the cited documents on 2026-11-07. Valid from 2026-03-01, the one effective date "
    "the documents state for the current NSE charge structure. Zerodha's page carries no effective "
    "dates, so BROKERAGE / DP_CHARGE / GST / SEBI are evidenced as 'published on retrieval date' only. "
    "Needs a person to verify each quote against its document. IPFT is inside the 0.00307%."
)
ASSUMED_NOTES = (
    "ASSUMED BACKFILL (opt-in; every run using it is flagged and cannot support promotion). Extends "
    "the CURRENT rates back to 2020-07-01 (the start of the uniform stamp duty). Evidence per item: "
    "STT - cash rates unchanged across NSE circulars 2016, 2023, 2024, 2026 (evidenced); stamp duty - "
    "uniform from 2020-07-01 (evidenced); NSE transaction - NOT evidenced for the client side: the "
    "exchange's member tariff was slab-based (about 3.00-3.45 per lakh) before Oct 2024 and a client "
    "rate may have differed; SEBI fee, GST, Zerodha brokerage and DP charge - no dated history "
    "captured. Costs in this period are approximate."
)
extra = ["nse_FATAX73524_delivery", "nse_FATAX73524_intraday", "nse_FATAX63809_cash_unchanged",
         "nse_FATAX56235_cash_unchanged", "nse_FATAX32385_cash_unchanged", "nse_stamp_duty",
         "nse_stamp_duty_effective", "nse_sebi_turnover_fee", "nse_gst", "nse_FA73061_cash_market",
         "nse_FA73061_effective", "nse_FA56129_member_slabs", "zerodha_sebi_pending_note",
         "zerodha_ipft", "zerodha_contract_note_minimum"]  # fmt: skip

a.out.mkdir(parents=True, exist_ok=True)
current = [schedule(p, id_=f"nse-cash-{p.lower()}-zerodha-2026-03-01", valid_from="2026-03-01", valid_until=None,
                    status="extracted_unverified", notes=CURRENT_NOTES, keys=sorted(set(used(p)) | set(extra)))
           for p in ("DELIVERY", "INTRADAY")]  # fmt: skip
assumed = [schedule(p, id_=f"nse-cash-{p.lower()}-zerodha-assumed-2020-07-01", valid_from="2020-07-01",
                    valid_until="2026-02-28", status="assumed_backfill", notes=ASSUMED_NOTES,
                    keys=sorted(set(used(p)) | set(extra)))
           for p in ("DELIVERY", "INTRADAY")]  # fmt: skip
(a.out / "nse_cash_zerodha.json").write_text(
    json.dumps({"schedules": current}, indent=2, ensure_ascii=False) + "\n"
)
(a.out / "assumed_backfill_nse_cash_zerodha.json").write_text(
    json.dumps({"schedules": assumed}, indent=2, ensure_ascii=False) + "\n"
)
print("wrote", [p.name for p in sorted(a.out.glob("*.json"))])
