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


MIN_ROWS = 100  # a daily file with fewer rows than this is not a plausible end-of-day file
CHAIN_BREAK = "CHAIN_BREAK"
SHORT_FILE = "SHORT_FILE"
DUPLICATE_ROWS = "DUPLICATE_ROWS"


@dataclass(frozen=True)
class Finding:
    kind: str
    day: date
    detail: str


def file_findings(
    files: Mapping[date, LegacyBhav], records: Mapping[date, Record]
) -> tuple[list[Finding], dict[date, tuple[date, int, int]]]:
    """Findings about the files themselves, never forced into agreement:
      FILE_DATE_MISMATCH  a file dated another day (from classify)
      DUPLICATE_ROWS      the same (symbol, series) twice in one file
      SHORT_FILE          implausibly few rows
      CHAIN_BREAK         two consecutive confirmed sessions (only closures between them) whose
                          PREVCLOSE/CLOSE chain falls below the threshold: a missing session, a
                          corporate-action cluster or bad data
    Also returns, per confirmed session, (previous session, symbols in both, symbols equal)."""
    out: list[Finding] = []
    links: dict[date, tuple[date, int, int]] = {}
    confirmed = sorted(d for d, f in files.items() if f.days == {d})  # weekend sessions too
    for d in sorted(files):
        f = files[d]
        if records.get(d) is not None and records[d].status == MISMATCH:
            out.append(Finding(MISMATCH, d, f"file dated {sorted(f.days)}"))
        if f.duplicates:
            out.append(Finding(DUPLICATE_ROWS, d, f"{f.duplicates} repeated (symbol, series) rows"))
        if f.rows < MIN_ROWS:
            out.append(Finding(SHORT_FILE, d, f"{f.rows} rows"))
    for a, b in zip(confirmed, confirmed[1:], strict=False):
        between = [d for d in records if a < d < b]
        if any(records[d].status != CLOSED for d in between):
            continue  # a weekday between them is unexamined or unexplained: nothing to chain yet
        both, eq = chain(files[a].close, files[b].prev_close)
        links[b] = (a, both, eq)
        if both < MIN_SYMBOLS or eq / both < CHAIN_THRESHOLD:
            out.append(
                Finding(
                    CHAIN_BREAK, b, f"{eq}/{both} closes equal the next day's PREVCLOSE after {a}"
                )
            )
    return out, links
