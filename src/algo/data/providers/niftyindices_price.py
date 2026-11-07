"""NSE Indices price-index history: POST /BackPage/getHistoricaldatatabletoString, the same
`cinfo` body as the Total Returns endpoint (see niftyindices_tri). The reply is a JSON array,
newest first: INDEX_NAME, HistoricalDate ('30 Oct 2026'), OPEN / HIGH / LOW ('-' in early years),
CLOSE ('13183.95') and a per-response RequestNumber that is ignored everywhere.

Only CLOSE is the benchmark level; OPEN/HIGH/LOW stay in the untouched raw response. Observations
reuse the TRI `Observation` (net_level is always None) so windows, request body and the normalized
hash are shared; a PRICE series is never mixed with a TRI series (each is its own benchmark)."""

from __future__ import annotations

import json

from algo.data.providers.niftyindices_tri import (
    MAX_DAYS,
    Observation,
    TriError,
    _level,
    normalized_hash,
    parse_date,
    request_body,
    windows,
)

ENDPOINT = "https://www.niftyindices.com/BackPage/getHistoricaldatatabletoString"
ENDPOINT_VERSION = "2026-11"
PARSER_VERSION = "1"
__all__ = ["ENDPOINT", "MAX_DAYS", "normalized_hash", "parse_response", "request_body", "windows"]


def parse_response(raw: bytes) -> list[Observation]:
    """Every row must be well formed or the whole response is refused (nothing is skipped)."""
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as e:
        raise TriError(f"not JSON: {e}") from e
    if not isinstance(rows, list):
        raise TriError("expected a JSON array")
    out = []
    for r in rows:
        if not isinstance(r, dict) or not {"HistoricalDate", "CLOSE"} <= r.keys():
            raise TriError(f"row without HistoricalDate / CLOSE: {r!r}")
        out.append(Observation(parse_date(r["HistoricalDate"]), _level(r["CLOSE"], "CLOSE"), None))
    return out
