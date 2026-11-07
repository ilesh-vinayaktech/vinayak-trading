"""Historical exchange-calendar evidence for weekdays, from the exchange's own daily files.

Four independent questions are kept apart and never merged:
  1. did the exchange trade?            this module (a file dated that day; or the lack of one)
  2. what kind of session was it?       NOT established here
  3. opening and closing times?         NOT established here
  4. is instrument-level data present?  the stored file itself (recorded, not judged)

A file whose TIMESTAMP is the date proves trading. A MISSING file proves nothing alone (the archive
can have gaps): closure is INFERRED only when the sessions on either side chain (the later file's
PREVCLOSE equals the earlier file's CLOSE for almost every symbol), because a session in between
would have changed the closes. That is an inference from exchange files, not an official holiday
notice, and is labelled as such."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from algo.data.providers.nse_bhavcopy_legacy import LegacyBhav, chain

TRADED = "TRADED_CONFIRMED"
MISMATCH = "FILE_DATE_MISMATCH"  # a file exists but is dated another day
CLOSED = "CLOSED_INFERRED_BY_CHAIN"  # no file, and the sessions either side chain
GAP = "SESSION_LIKELY_ARCHIVE_GAP"  # no file, and the sessions either side do NOT chain
UNEXAMINED = "UNEXAMINED"  # not fetched, or no confirmed session on one side yet
CHAIN_THRESHOLD = 0.95  # genuine consecutive sessions agree on ~100%; a session between differs
MIN_SYMBOLS = 20


@dataclass(frozen=True)
class Record:
    status: str
    earlier: date | None = None  # nearest confirmed session before (for CLOSED / GAP)
    later: date | None = None
    symbols_in_both: int = 0
    symbols_equal: int = 0


def classify(
    weekdays: Iterable[date],
    files: Mapping[date, LegacyBhav],
    missing: frozenset[date] | set[date],
) -> dict[date, Record]:
    traded = sorted(d for d, f in files.items() if f.days == {d})
    cache: dict[tuple[date, date], tuple[int, int]] = {}
    out: dict[date, Record] = {}
    for d in weekdays:
        if d in files:
            out[d] = Record(TRADED if files[d].days == {d} else MISMATCH)
            continue
        if d not in missing:
            out[d] = Record(UNEXAMINED)
            continue
        before = [x for x in traded if x < d]
        after = [x for x in traded if x > d]
        if not before or not after:
            out[d] = Record(UNEXAMINED)
            continue
        a, b = before[-1], after[0]
        if (a, b) not in cache:
            cache[(a, b)] = chain(files[a].close, files[b].prev_close)
        both, eq = cache[(a, b)]
        chained = both >= MIN_SYMBOLS and eq / both >= CHAIN_THRESHOLD
        out[d] = Record(CLOSED if chained else GAP, a, b, both, eq)
    return out
