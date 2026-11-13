"""Synthetic quarterly filings for integration tests: one stock, one EPS figure, a filing per quarter-end, filed 45 days after."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D

import psycopg

EPS = "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations"


def add_filings(
    conn: psycopg.Connection,
    iid: int,
    symbol: str,
    isin: str,
    eps: float,
    ends: list[date],
    now: datetime,
) -> None:
    for n, end in enumerate(ends):
        fid = conn.execute(
            "INSERT INTO fundamental_filing (symbol,isin,instrument_id,seq_number,period_start,period_end,basis,audited,bank,"
            "filed_at,rounding,xbrl_url,raw_sha256,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,'CONSOLIDATED',false,false,%s,'',%s,%s,%s)"
            " RETURNING filing_id",
            (symbol, isin, iid, n, end - timedelta(days=90), end,
             datetime.combine(end + timedelta(days=45), time(10), UTC), "u", f"h{symbol}{n}", now),
        ).fetchone()[0]  # fmt: skip
        conn.cursor().executemany(
            "INSERT INTO fundamental_fact (filing_id, metric, scope, value) VALUES (%s,%s,'QUARTER',%s)",
            [
                (fid, EPS, D(str(eps))),
                (fid, "PaidUpValueOfEquityShareCapital", D(1000)),
                (fid, "FaceValueOfEquityShareCapital", D(10)),
            ],
        )
