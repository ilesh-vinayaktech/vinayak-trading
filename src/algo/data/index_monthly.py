"""Store the parsed monthly constituent snapshots, with every symbol resolved through the instrument
alias history (as of the report date). Unresolved symbols stay visible."""

from __future__ import annotations

import hashlib
import io
import re
import subprocess
import zipfile
from collections.abc import Sequence
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from algo.core.clock import require_utc
from algo.data.index_releases import map_symbol
from algo.data.providers.nse_index_monthly import (
    PARSER_VERSION,
    IndexSnapshot,
    extract_words,
    parse_snapshot,
)

# normalised PDF file stem -> what it is. Everything else in the archive is kept but not parsed.
WANTED = {
    "nifty50": "NIFTY_50", "niftynext50": "NIFTY_NEXT_50", "nifty100": "NIFTY_100",
    "niftymidcap100": "MIDCAP_100", "niftyfreefloatmidcap100": "MIDCAP_100_FREE_FLOAT",
    "niftyfullmidcap100": "MIDCAP_100_FULL", "nifty200": "NIFTY_200",
}  # fmt: skip
_SUFFIX = re.compile(
    r"_?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*_?\d{4}\.pdf$", re.I
)


def stem(filename: str) -> str:
    """'NIFTY_Next_50_Mar2020.pdf' and 'niftynext50_Jan2017.pdf' both -> 'niftynext50'."""
    return re.sub(r"[^a-z0-9]", "", _SUFFIX.sub("", filename.rsplit("/", 1)[-1]).lower())


def select_pdfs(names: list[str]) -> dict[str, str]:
    """component -> PDF file name, for the indices we parse."""
    return {WANTED[stem(n)]: n for n in names if n.lower().endswith(".pdf") and stem(n) in WANTED}


def store_snapshot(
    conn: psycopg.Connection, snap: IndexSnapshot, *, zip_hash: str, pdf_name: str, pdf_hash: str,
    now: datetime,
) -> int:  # fmt: skip
    """Idempotent per (index, report date, parser version). Returns constituents stored."""
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO index_monthly_snapshot (index_name,component,as_of,zip_hash,pdf_name,"
            "pdf_hash,parser_version,problems,parsed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT DO NOTHING RETURNING snapshot_id",
            (snap.index_name, snap.component, snap.as_of, zip_hash, pdf_name, pdf_hash,
             PARSER_VERSION, Jsonb(list(snap.problems)), require_utc(now)),
        ).fetchone()  # fmt: skip
        if row is None:
            return 0
        for r in snap.rows:
            iid, status = map_symbol(conn, r.symbol, snap.as_of)
            conn.execute(
                "INSERT INTO index_monthly_constituent VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (row[0], r.symbol, r.name, r.industry, r.price, r.index_mcap, r.weight, r.page,
                 iid, "MAPPED" if status == "MAPPED" else "UNMAPPED_SYMBOL"),
            )  # fmt: skip
    return len(snap.rows)


def parse_archive(
    conn: psycopg.Connection, zip_bytes: bytes, now: datetime
) -> tuple[list[str], list[str]]:
    """Parse and store the wanted PDFs of one monthly archive. Returns (stored index names,
    problems). A PDF whose printed title disagrees with its file name is reported, not trusted."""
    zhash = hashlib.sha256(zip_bytes).hexdigest()
    stored: list[str] = []
    problems: list[str] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        wanted = select_pdfs(z.namelist())
        for component, name in sorted(wanted.items()):
            data = z.read(name)
            try:
                snap = parse_snapshot(extract_words(data))
            except (ValueError, subprocess.CalledProcessError) as e:
                problems.append(
                    f"{name}: unreadable PDF ({e})"
                    if not isinstance(e, ValueError)
                    else f"{name}: {e}"
                )
                continue
            if snap.component != component:
                problems.append(f"{name}: file name says {component}, title says {snap.component}")
                continue
            store_snapshot(conn, snap, zip_hash=zhash, pdf_name=name,
                           pdf_hash=hashlib.sha256(data).hexdigest(), now=now)  # fmt: skip
            stored.append(snap.index_name)
            problems += [f"{name}: {p}" for p in snap.problems]
    return stored, problems


def remap_monthly(conn: psycopg.Connection, symbols: Sequence[str] | None = None) -> int:
    """Re-resolve constituents still UNMAPPED after an alias was added (the `map_symbol` rule: the
    alias must be valid on the snapshot date), optionally only for these symbols. Idempotent."""
    return conn.execute(
        "UPDATE index_monthly_constituent k SET instrument_id=a.instrument_id,"
        " mapping_status='MAPPED' FROM index_monthly_snapshot s, instrument_alias a"
        " WHERE k.snapshot_id=s.snapshot_id"
        " AND k.mapping_status='UNMAPPED_SYMBOL' AND a.source='nse' AND a.source_symbol=k.symbol"
        " AND a.valid_from <= s.as_of AND (a.valid_to IS NULL OR s.as_of < a.valid_to)"
        " AND (%s::text[] IS NULL OR k.symbol = ANY(%s::text[]))",
        (symbols, symbols),
    ).rowcount
