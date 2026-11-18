# ruff: noqa: E501
"""Which stocks make up an index, from the official constituent lists NSE publishes (stored untouched in the raw lake by `capture_index_lists.py` and
`capture_current_lists.py`). A list is a CSV of company, industry, symbol, series and ISIN. Indices without a list (the BSE Sensex, India VIX, bond and
strategy indices) have no members here and say so rather than guess."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# index symbol (as Kite and index_bar_1d name it) -> lake dataset holding its list
LISTS = {
    "NIFTY 50": "nifty50_list",
    "NIFTY NEXT 50": "niftynext50_list",
    "NIFTY MIDCAP 100": "niftymidcap100_list",
    "NIFTY 200": "nifty200_list",
    "NIFTY 500": "nifty500_list",
    "NIFTY 100": "nifty100_list",
    "NIFTY SMLCAP 100": "niftysmallcap100_list",
    "NIFTY BANK": "niftybank_list",
    "NIFTY PVT BANK": "niftyprivatebank_list",
    "NIFTY PSU BANK": "niftypsubank_list",
    "NIFTY FIN SERVICE": "niftyfinancialservices_list",
    "NIFTY IT": "niftyit_list",
    "NIFTY PHARMA": "niftypharma_list",
    "NIFTY HEALTHCARE": "niftyhealthcare_list",
    "NIFTY AUTO": "niftyauto_list",
    "NIFTY FMCG": "niftyfmcg_list",
    "NIFTY CONSUMPTION": "niftyconsumption_list",
    "NIFTY CONSR DURBL": "niftyconsumerdurables_list",
    "NIFTY METAL": "niftymetal_list",
    "NIFTY REALTY": "niftyrealty_list",
    "NIFTY ENERGY": "niftyenergy_list",
    "NIFTY OIL AND GAS": "niftyoilgas_list",
    "NIFTY INFRA": "niftyinfrastructure_list",
    "NIFTY MEDIA": "niftymedia_list",
    "NIFTY PSE": "niftypse_list",
    "NIFTY COMMODITIES": "niftycommodities_list",
    "NIFTY INDIA MFG": "niftyindiamanufacturing_list",
    "NIFTY MNC": "niftymnc_list",
}
# the file each dataset is published as, under https://www.niftyindices.com/IndexConstituent/ (used by the capture script)
FILES = {
    "nifty50_list": "ind_nifty50list.csv",
    "niftynext50_list": "ind_niftynext50list.csv",
    "niftymidcap100_list": "ind_niftymidcap100list.csv",
    "nifty200_list": "ind_nifty200list.csv",
    "nifty500_list": "ind_nifty500list.csv",
    "nifty100_list": "ind_nifty100list.csv",
    "niftysmallcap100_list": "ind_niftysmallcap100list.csv",
    "niftybank_list": "ind_niftybanklist.csv",
    "niftyprivatebank_list": "ind_nifty_privatebanklist.csv",
    "niftypsubank_list": "ind_niftypsubanklist.csv",
    "niftyfinancialservices_list": "ind_niftyfinancelist.csv",
    "niftyit_list": "ind_niftyitlist.csv",
    "niftypharma_list": "ind_niftypharmalist.csv",
    "niftyhealthcare_list": "ind_niftyhealthcarelist.csv",
    "niftyauto_list": "ind_niftyautolist.csv",
    "niftyfmcg_list": "ind_niftyfmcglist.csv",
    "niftyconsumption_list": "ind_niftyconsumptionlist.csv",
    "niftyconsumerdurables_list": "ind_niftyconsumerdurableslist.csv",
    "niftymetal_list": "ind_niftymetallist.csv",
    "niftyrealty_list": "ind_niftyrealtylist.csv",
    "niftyenergy_list": "ind_niftyenergylist.csv",
    "niftyoilgas_list": "ind_niftyoilgaslist.csv",
    "niftyinfrastructure_list": "ind_niftyinfralist.csv",
    "niftymedia_list": "ind_niftymedialist.csv",
    "niftypse_list": "ind_niftypselist.csv",
    "niftycommodities_list": "ind_niftycommoditieslist.csv",
    "niftyindiamanufacturing_list": "ind_niftyindiamanufacturinglist.csv",
    "niftymnc_list": "ind_niftymnclist.csv",
}


@dataclass(frozen=True)
class Member:
    symbol: str
    name: str
    industry: str
    isin: str


def members(lake_root: Path, index_symbol: str) -> tuple[date, list[Member]] | None:
    """(the date the list was captured, its stocks) from the newest stored list of this index; None when no list is stored for it."""
    dataset = LISTS.get(index_symbol)
    if dataset is None:
        return None
    folders = sorted((lake_root / "raw/niftyindices" / dataset).glob("dt=*"))
    if not folders:
        return None
    files = sorted(folders[-1].glob("v*.bin"), key=lambda p: int(p.stem[1:]))
    if not files:
        return None
    rows = csv.DictReader(io.StringIO(files[-1].read_bytes().decode("utf-8-sig")))
    out = [
        Member(
            r["Symbol"].strip(),
            r["Company Name"].strip(),
            r.get("Industry", "").strip(),
            r["ISIN Code"].strip(),
        )
        for r in rows
        if r.get("Symbol")
    ]
    return date.fromisoformat(folders[-1].name[3:]), out
