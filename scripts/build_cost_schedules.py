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
s_fa46730 = src(
    "nse_FA46730_cash_market",
    "nse_FA46730",
    "Upto 1250 Crores Rs 3.25 each side Rs 3.45 each side",
    "Cash Market table, first slab: existing vs revised MEMBER tariff (per lakh of traded value), not a client rate",
)
s_fa46730_dt = src(
    "nse_FA46730_effective",
    "nse_FA46730",
    "The above revision in transaction charges will be applicable with effect from January 01, 2021.",
    "Circular NSE/FA/46730 dated 18 Dec 2020",
)
s_sebi_gst = src(
    "sebi_gst_circular_subject",
    "sebi_gst_circular_2022_07_18",
    "Levy of Goods & Services Tax (GST) on the fees payable to SEBI",
    "Circular SEBI/HO/GSD/TAD/CIR/P/2022/0097 dated 18 Jul 2022, subject line",
)
s_sebi_gst_dt = src(
    "sebi_gst_circular_effective",
    "sebi_gst_circular_2022_07_18",
    "with effect from July 18, 2022.",
    "Same circular: fees payable to SEBI are subject to GST at 18% from this date",
)


s_free_2015 = src(
    "zerodha_zero_brokerage_since_2015",
    "zerodha_zero_brokerage_2015",
    "Starting 1st December 2015, all investments at Zerodha will be absolutely free.",
    "Zerodha blog: Brokerage Edge (equity delivery: zero brokerage from 1 Dec 2015; no later change recorded)",
)
s_txn_2023 = src(
    "zerodha_bulletin_2023_04_txn",
    "zerodha_bulletin_2023_04",
    "NSE Equity – Delivery 0.00345% 0.00325%",
    "Bulletin 'Revision in transaction charges and STT from 1st April 2023': delivery 0.00345% -> 0.00325%, with effect from April 1, 2023",
)
s_txn_2023_dt = src(
    "zerodha_bulletin_2023_04_effective",
    "zerodha_bulletin_2023_04",
    "There is also a revision in Securities Transaction Tax (STT) with effect from April 1, 2023.",
    "Same bulletin (title: from 1st April 2023). The 0.00345% before it is the 'old' rate; its own start date is not stated",
)
s_txn_2024a = src(
    "zerodha_bulletin_2024_04_txn",
    "zerodha_bulletin_2024_04",
    "NSE Equity Delivery 0.00325% 0.00322%",
    "Bulletin 'Revision in NSE transaction charges from April 1, 2024': delivery 0.00325% -> 0.00322%",
)
s_txn_2024a_dt = src(
    "zerodha_bulletin_2024_04_effective",
    "zerodha_bulletin_2024_04",
    "Revision in NSE transaction charges from April 1, 2024",
    "Bulletin title",
)
s_txn_2024b = src(
    "zerodha_bulletin_2024_10_txn",
    "zerodha_bulletin_2024_10",
    "NSE Equity Delivery 0.00322% (or ₹3.22 per lakh) 0.00297% (or ₹2.97 per lakh)",
    "Bulletin 'Revision in transaction charges and STT from 1st October 2024': delivery 0.00322% -> 0.00297%",
)
s_txn_2024b_dt = src(
    "zerodha_bulletin_2024_10_effective",
    "zerodha_bulletin_2024_10",
    "Revision in transaction charges and STT from 1st October 2024",
    "Bulletin title",
)
s_dp_13 = src(
    "zerodha_bulletin_2024_10_dp_fee",
    "zerodha_bulletin_2024_10",
    "Debit transactions in the demat account are charged a fee of ₹13 per debit. Effective October 1, 2024, the composition of this fee has been revised from ₹5 depository fee + ₹8 depository participant fee to ₹3.5 depository fee + ₹9.5 depository participant fee.",
    "Same bulletin: the fee was Rs 13 per debit before and after 1 Oct 2024 (only its split changed). Rs 13 + 18% GST = Rs 15.34. Not evidenced before the period this bulletin describes",
)

s_dp_2016 = src(
    "zerodha_forum_dp_2016",
    "zerodha_forum_dp_2016",
    "At Zerodha DP charge is a flat Rs 13.5 per scrip per day sold (irrespective of the quantity sold).",
    "Zerodha's founder answering on Zerodha's official forum, March 2016 (taxes additional; Rs 8 Zerodha + Rs 5.5 CDSL)",
)
s_dp_2017 = src(
    "zerodha_forum_dp_2017",
    "zerodha_forum_dp_2017",
    "only on the day you sell you are charged Rs 13.5",
    "Zerodha's founder, same forum, September 2017",
)
s_dp_2024 = src(
    "zerodha_forum_dp_2024",
    "zerodha_forum_dp_2024",
    "effective June 01, 2024, the DP charges will be reduced from Rs.13.5 to Rs.13",
    "Forum thread of May 2024, reply by a Zerodha team member relaying CDSL's 50-paise reduction: secondhand, no CDSL or Zerodha dated notice",
)
s_dp_once = src(
    "zerodha_support_dp_once_per_scrip_per_day",
    "zerodha_support_dp_charges",
    "2:00 PM: You sell another 50 shares of Reliance. DP charges: ₹13 + 18% GST = ₹15.34.",
    "Zerodha support page, worked example: two sales of one scrip on one day are charged the depository fee once",
)

s_sebi_50 = src(
    "nse_FA44514_sebi_half_fee",
    "nse_FA44514",
    "pay only 50% (fifty percent) of fees as calculated therein",
    "SEBI notification SEBI/LAD-NRO/GN/2020/011 of 8 May 2020 (in force 1 Jun 2020), clause (1A): brokers pay half the turnover fee for the period 1 Jun 2020 to 31 Mar 2021 (the turnover fee is Rs 10 per crore)",
)
s_sebi_50_period = src(
    "nse_FA44514_sebi_half_fee_period",
    "nse_FA44514",
    "for the period June 01, 2020 to March 31, 2021",
    "Same clause: the dates of the reduction",
)
s_z2020_txn = src(
    "zerodha_page_2020_09_29_txn",
    "zerodha_charges_wayback_2020_09_29",
    "Transaction charges NSE: 0.00325% BSE: 0.003%",
    "Zerodha's own charges page as archived by the Internet Archive on 2020-09-29, equity delivery column",
)
s_z2020_sebi = src(
    "zerodha_page_2020_09_29_sebi",
    "zerodha_charges_wayback_2020_09_29",
    "SEBI charges ₹5 / crore",
    "Same archived page: the halved SEBI fee",
)
s_z2020_dp = src(
    "zerodha_page_2020_09_29_dp",
    "zerodha_charges_wayback_2020_09_29",
    "DP (Depository participant) charges ₹13.5 + GST per scrip (irrespective of quantity), on the day",
    "Same archived page: the depository charge on 2020-09-29",
)
s_z2020_gst = src(
    "zerodha_page_2020_09_29_gst",
    "zerodha_charges_wayback_2020_09_29",
    "GST 18% on (brokerage + transaction charges)",
    "Same archived page: GST is charged on brokerage and transaction charges, not on the SEBI fee",
)

s_z2021_txn = src(
    "zerodha_page_2021_04_11_txn",
    "zerodha_charges_wayback_2021_04_11",
    "Transaction charges NSE: 0.00345% BSE: 0.00345%",
    "Zerodha's own charges page as archived by the Internet Archive on 2021-04-11, equity delivery column",
)
s_z2021_sebi = src(
    "zerodha_page_2021_04_11_sebi",
    "zerodha_charges_wayback_2021_04_11",
    "SEBI charges ₹5 / crore",
    "Same archived page: Zerodha was still billing the halved SEBI fee on 2021-04-11 (it charged the April to May difference to the ledger afterwards)",
)
s_z2021_dp = src(
    "zerodha_page_2021_04_11_dp",
    "zerodha_charges_wayback_2021_04_11",
    "DP (Depository participant) charges ₹13.5 + GST per scrip (irrespective of quantity), on the day",
    "Same archived page: the depository charge on 2021-04-11",
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
    evidence="EXTRACTED_UNVERIFIED",
):
    d = {"type": type_, "basis": basis, "side": side, "taxable_for_gst": gst, "gst_inclusive": incl,
         "rounding": "HALF_UP_2DP", "source": source, "evidence": evidence}  # fmt: skip
    for k, v in (
        ("rate_pct", rate),
        ("amount", amount),
        ("minimum", minimum),
        ("maximum", maximum),
    ):
        if v is not None:
            d[k] = v
    return d


def delivery_components(
    *,
    txn: str,
    txn_src: str,
    gst: bool,
    sebi_gst: bool,
    dp: str,
    dp_incl: bool,
    stamp_src: str,
    ev: dict[str, str] | None = None,
    dp_src: str | None = None,
    sebi_rate: str = "0.0001",
    sebi_src: str | None = None,
) -> list[dict]:
    """One dated delivery schedule: the rates that changed over time are arguments, the rest is as in the current schedule."""
    ev = ev or {}
    out = [
        comp("BROKERAGE", "TRADE_VALUE", "BOTH", rate="0", gst=gst, source=s_free_2015),
        comp("STT", "TRADE_VALUE", "BOTH", rate="0.1", source=s_stt_del),
        comp(
            "EXCHANGE_TRANSACTION",
            "TRADE_VALUE",
            "BOTH",
            rate=txn,
            gst=gst,
            source=txn_src,
            evidence=ev.get("EXCHANGE_TRANSACTION", "EXTRACTED_UNVERIFIED"),
        ),
        comp(
            "SEBI_TURNOVER",
            "TRADE_VALUE",
            "BOTH",
            rate=sebi_rate,
            gst=gst and sebi_gst,
            source=sebi_src or s_sebi,
        ),
        comp(
            "STAMP_DUTY",
            "TRADE_VALUE",
            "BUY",
            rate="0.015",
            source=stamp_src,
            evidence=ev.get("STAMP_DUTY", "EXTRACTED_UNVERIFIED"),
        ),
        comp(
            "DP_CHARGE",
            "PER_SCRIP",
            "SELL",
            amount=dp,
            incl=dp_incl,
            source=dp_src or s_dp_13,
            evidence=ev.get("DP_CHARGE", "EXTRACTED_UNVERIFIED"),
        ),
    ]
    if gst:
        out.append(comp("GST", "GST_BASE", "BOTH", rate="18", source=s_gst))
    return out


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
        "id": id_, "version": "2026-11-15.1", "account_scope": "RESIDENT_INDIVIDUAL_RETAIL", "name": f"NSE cash equity {product.lower()} via Zerodha",
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
           for p in ("INTRADAY",)]  # delivery now has its own dated history below  # fmt: skip

# ---- equity DELIVERY history, one schedule per period in which any rate differed --------------------------------------------
EVIDENCE = (
    "Evidenced from stored documents: STT 0.1% each side (NSE circulars 2016/2023/2024/2026: no change), zero delivery brokerage "
    "(Zerodha, from 1 Dec 2015), the NSE transaction rate and the dates it changed (Zerodha bulletins Apr 2023, Apr 2024, Oct 2024; "
    "NSE circulars Dec 2020 and Mar 2026), stamp duty 0.015% on the buy side from 1 Jul 2020 (NSE), GST on fees payable to SEBI from 18 Jul 2022 "
    "(SEBI circular), SEBI fee Rs 10/crore and GST 18% (Zerodha and NSE pages, undated: read on the retrieval date), DP fee Rs 13 per debit "
    "just before and after 1 Oct 2024 (Zerodha bulletin). Each component carries its own evidence status; a schedule can be verified only when none is ASSUMED. "
)
X, A, E = "EXTRACTED_UNVERIFIED", "ASSUMED", "EXCHANGE_TRANSACTION"
A_STAMP = "Stamp duty before 1 July 2020 was set by each state. The uniform 0.015% is applied instead as a modelling assumption: it may overstate the cost, and the state treatment is not recovered."
A_SERVICE_TAX = "Service tax (about 15%) on the exchange fee and the depository charge before GST began on 1 July 2017 is not modelled."
A_TXN_PRE2021 = (
    "For 1 July 2020 to 31 December 2020 and every earlier period the exchange fee is taken as 0.00325%: NSE's MEMBER tariff before circular NSE/FA/46730 took effect (Rs 3.25 per lakh, first slab). "
    "That is an ASSUMPTION about the Zerodha client rate, not evidence of it. A temporary concession for EQ-series stocks outside Nifty 50 and Next 50 (FA45147 from 1 Aug 2020, extended by FA47844, "
    "FA49796 and FA51855) is unresolved: whether it reached Zerodha clients is not known."
)
A_TXN_2021 = (
    "The Zerodha client rate of 0.00345% is read from Zerodha's own charges page of 2021-04-11 (archived). That it began on 1 January 2021 is an inference: that is the day NSE's member "
    "tariff moved (NSE/FA/46730). Zerodha's own notice of the change was not found."
)
A_TXN_2020 = (
    "The exchange fee of 0.00325% is read from Zerodha's own charges page of 2020-09-29 (archived). That it applied for the whole of 1 July to 31 December 2020 is an inference: "
    "NSE moved its member tariff only on 1 January 2021 (NSE/FA/46730). The temporary EQ-series concession (FA45147, FA47844) is unresolved: whether it reached clients is not known."
)
A_SEBI_2020 = (
    "The SEBI turnover fee is Rs 5 per crore from 1 June 2020 to 31 March 2021 (SEBI notification SEBI/LAD-NRO/GN/2020/011, via NSE/FA/44514, and Zerodha's page of 2020-09-29). "
    "Zerodha kept billing Rs 5 until 4 May 2021 and then charged the April to May difference to the ledger (a Zerodha staff reply on its forum), so from 1 April 2021 the schedule uses Rs 10."
)
A_DP = (
    "The depository charge before 1 June 2024 is taken as Rs 13.50 (Rs 8 Zerodha + Rs 5.50 CDSL) plus GST from 1 July 2017 (Rs 15.93). It is evidenced by Zerodha's founder on Zerodha's forum in March 2016 and "
    "September 2017; its continuation unchanged to 31 May 2024 is an assumption."
)
A_DP_JUN24 = (
    "The depository charge is taken as Rs 13 plus GST (Rs 15.34) from 1 June 2024. The date rests on a forum reply by a Zerodha team member relaying a reported 50-paise CDSL reduction, "
    "and on Zerodha's September 2024 bulletin giving Rs 13 immediately before 1 October 2024. No CDSL or Zerodha dated notice of the change was found."
)
# id suffix, from, until, txn %, txn source, GST on charges, GST on the SEBI fee, (DP amount, GST included), stamp source, evidence overrides, assumptions, caveat
PERIODS = [
    ("2016-01-01", "2016-01-01", "2017-06-30", "0.00325", s_fa46730, False, False, ("13.5", False), s_stamp_nse,
     {E: A, "STAMP_DUTY": A, "DP_CHARGE": A}, [A_STAMP, A_SERVICE_TAX, A_TXN_PRE2021, A_DP], s_dp_2016,
     "Before GST (1 Jul 2017) service tax applied; it is NOT modelled. Stamp duty before 1 Jul 2020 was state-specific: the uniform 0.015% is an assumption."),
    ("2017-07-01", "2017-07-01", "2020-05-31", "0.00325", s_fa46730, True, False, ("15.93", True), s_stamp_nse,
     {E: A, "STAMP_DUTY": A, "DP_CHARGE": A}, [A_STAMP, A_TXN_PRE2021, A_DP], s_dp_2017,
     "GST 18% on brokerage and the exchange fee from 1 Jul 2017; the SEBI fee is outside GST until 18 Jul 2022 (SEBI circular; Zerodha's own page of 2020-09-29 also bases GST on brokerage and transaction charges only). Stamp duty before 1 Jul 2020 was state-specific: the uniform 0.015% is an assumption."),
    ("2020-06-01", "2020-06-01", "2020-06-30", "0.00325", s_fa46730, True, False, ("15.93", True), s_stamp_nse,
     {E: A, "STAMP_DUTY": A, "DP_CHARGE": A}, [A_STAMP, A_TXN_PRE2021, A_DP, A_SEBI_2020], s_dp_2017,
     "The SEBI turnover fee is halved from 1 Jun 2020 (SEBI notification). Stamp duty before 1 Jul 2020 was state-specific: the uniform 0.015% is an assumption."),
    ("2020-07-01", "2020-07-01", "2020-12-31", "0.00325", s_z2020_txn, True, False, ("15.93", True), s_stamp_nse,
     {"DP_CHARGE": A}, [A_TXN_2020, A_DP, A_SEBI_2020], s_z2020_dp,
     "The SEBI fee is halved (SEBI notification) and outside GST until 18 Jul 2022. The exchange fee and the Rs 13.50 depository charge are on Zerodha's own page of 2020-09-29."),
    ("2021-01-01", "2021-01-01", "2021-03-31", "0.00345", s_z2021_txn, True, False, ("15.93", True), s_stamp_nse,
     {"DP_CHARGE": A}, [A_TXN_2021, A_DP, A_SEBI_2020], s_z2021_dp,
     "The SEBI fee is halved until 31 Mar 2021 (SEBI notification) and outside GST until 18 Jul 2022. 0.00345% is the rate Zerodha's April 2023 bulletin gives as the one before that date; NSE/FA/46730 dates NSE's own change to 1 Jan 2021."),
    ("2021-04-01", "2021-04-01", "2022-07-17", "0.00345", s_z2021_txn, True, False, ("15.93", True), s_stamp_nse,
     {"DP_CHARGE": A}, [A_TXN_2021, A_DP], s_z2021_dp,
     "The SEBI fee is back to Rs 10 per crore from 1 Apr 2021 and outside GST until 18 Jul 2022 (SEBI circular). 0.00345% is the rate Zerodha's April 2023 bulletin gives as the one before that date."),
    ("2022-07-18", "2022-07-18", "2023-03-31", "0.00345", s_txn_2023, True, True, ("15.93", True), s_stamp_nse,
     {"DP_CHARGE": A}, [A_DP], s_dp_2017, "GST on the SEBI fee from 18 Jul 2022 (SEBI circular)."),
    ("2023-04-01", "2023-04-01", "2024-03-31", "0.00325", s_txn_2023, True, True, ("15.93", True), s_stamp_nse,
     {"DP_CHARGE": A}, [A_DP], s_dp_2017, ""),
    ("2024-04-01", "2024-04-01", "2024-05-31", "0.00322", s_txn_2024a, True, True, ("15.93", True), s_stamp_nse,
     {"DP_CHARGE": A}, [A_DP], s_dp_2017, ""),
    ("2024-06-01", "2024-06-01", "2024-09-30", "0.00322", s_txn_2024a, True, True, ("15.34", True), s_stamp_nse,
     {"DP_CHARGE": A}, [A_DP_JUN24], s_dp_2024, ""),
    ("2024-10-01", "2024-10-01", "2026-02-28", "0.00297", s_txn_2024b, True, True, ("15.34", True), s_stamp_nse,
     {}, [], s_dp_13, ""),
]  # fmt: skip
HISTORY_SOURCES = ["zerodha_zero_brokerage_since_2015", "zerodha_bulletin_2023_04_txn", "zerodha_bulletin_2023_04_effective",
                   "zerodha_bulletin_2024_04_txn", "zerodha_bulletin_2024_04_effective", "zerodha_bulletin_2024_10_txn",
                   "zerodha_bulletin_2024_10_effective", "zerodha_bulletin_2024_10_dp_fee", "nse_FA46730_cash_market",
                   "nse_FA46730_effective", "sebi_gst_circular_subject", "sebi_gst_circular_effective",
                   "zerodha_forum_dp_2016", "zerodha_forum_dp_2017", "zerodha_forum_dp_2024", "zerodha_support_dp_once_per_scrip_per_day",
                   "nse_FA44514_sebi_half_fee", "nse_FA44514_sebi_half_fee_period", "zerodha_page_2020_09_29_txn", "zerodha_page_2020_09_29_sebi",
                   "zerodha_page_2020_09_29_dp", "zerodha_page_2020_09_29_gst", "zerodha_page_2021_04_11_txn",
                   "zerodha_page_2021_04_11_sebi", "zerodha_page_2021_04_11_dp"]  # fmt: skip
history = []
for suffix, frm, until, txn, txn_src, gst, sebi_gst, (
    dp,
    dp_incl,
), stamp_src, ev, assumptions, dp_src, caveat in PERIODS:
    comps = delivery_components(
        txn=txn,
        txn_src=txn_src,
        gst=gst,
        sebi_gst=sebi_gst,
        dp=dp,
        dp_incl=dp_incl,
        stamp_src=stamp_src,
        ev=ev,
        dp_src=dp_src,
        sebi_rate="0.00005" if frm >= "2020-06-01" and until <= "2021-03-31" else "0.0001",
        sebi_src=s_sebi_50 if frm >= "2020-06-01" and until <= "2021-03-31" else None,
    )
    entry = schedule("DELIVERY", id_=f"nse-cash-delivery-zerodha-{suffix}", valid_from=frm, valid_until=until, status="extracted_unverified",
                     notes=("HISTORICAL delivery rates for " + f"{frm} to {until}. " + EVIDENCE + (caveat or "Every rate in this period is evidenced as above.")),
                     keys=sorted({c["source"] for c in comps} | set(extra) | set(HISTORY_SOURCES)))  # fmt: skip
    if assumptions:
        entry["assumptions"] = assumptions
    entry["components"] = comps
    history.append(entry)

(a.out / "nse_cash_zerodha.json").write_text(
    json.dumps({"schedules": current}, indent=2, ensure_ascii=False) + "\n"
)
(a.out / "assumed_backfill_nse_cash_zerodha.json").write_text(
    json.dumps({"schedules": assumed}, indent=2, ensure_ascii=False) + "\n"
)
(a.out / "history_delivery_nse_cash_zerodha.json").write_text(
    json.dumps({"schedules": history}, indent=2, ensure_ascii=False) + "\n"
)
print("wrote", [p.name for p in sorted(a.out.glob("*.json"))])
