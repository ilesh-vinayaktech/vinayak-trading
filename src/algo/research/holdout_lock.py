# ruff: noqa: E501
"""The global research holdout lock (docs/vti-alignment.md section 3, docs/vti-phase1-spec.md work item A).

Research code never sees a day on or after `holdout_start`. Two parts:
  * the LOCK: dates in `config/research_holdout.json`, anchored in the database as a hash (`research_lock`, append-only). `require`
    compares the file with the newest row and FAILS CLOSED when there is no row or the two differ.
  * the GUARD: `ResearchReader` wraps a `BarReader`. What it loads holds no bar, corporate action or vendor-dividend date from the
    holdout (cut at the source, so no attribute can leak one), and a request whose end reaches the holdout is REFUSED, not silently
    cut, so a mistake shows up. Its surface is an allow-list: nothing else of the inner reader (the connection, raw rows) is reachable.
This stops accidents and ordinary code paths. It is not a defence against someone holding database credentials.
Not covered here yet: fundamentals filings, feature values (no feature store yet) and the evaluation batch (slice 2)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg

from algo.data.issuer_series import Link
from algo.data.minute_reader import minute_history
from algo.data.reader import BarReader, History, Loaded

LOCK_FILE = Path(__file__).resolve().parents[3] / "config" / "research_holdout.json"
_KEYS = ("development_end", "holdout_end", "holdout_start")


class HoldoutError(Exception):
    pass


class HoldoutAccess(HoldoutError):
    """Research code asked for a day inside the holdout."""


class LockMismatch(HoldoutError):
    """The lock is not anchored, is unreadable or invalid, or the file and the database disagree: every research reader refuses."""


@dataclass(frozen=True)
class Lock:
    development_end: date
    holdout_start: date
    holdout_end: date

    def __post_init__(self) -> None:
        if self.development_end >= self.holdout_start:
            raise LockMismatch("development must end before the holdout starts")
        if self.holdout_start > self.holdout_end:
            raise LockMismatch("the holdout starts not before it ends")

    @property
    def sha256(self) -> str:
        body = {k: getattr(self, k).isoformat() for k in _KEYS}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def from_file(path: Path | None = None) -> Lock:
    p = path or LOCK_FILE
    try:
        raw = json.loads(p.read_text())
        if set(raw) != set(_KEYS):
            raise ValueError(f"keys must be exactly {', '.join(_KEYS)}")
        return Lock(
            *(
                date.fromisoformat(raw[k])
                for k in ("development_end", "holdout_start", "holdout_end")
            )
        )
    except (OSError, ValueError, TypeError) as e:
        raise LockMismatch(f"cannot read the research lock file {p}: {e}") from e


def anchor(conn: psycopg.Connection, lock: Lock, *, by: str, reason: str, now: datetime) -> int:
    """Record the lock as the one in force (a new append-only row). Refuses nothing else yet: the rule 'no change after a holdout batch exists' arrives with the batch table."""
    row = conn.execute(
        "INSERT INTO research_lock (config_sha256, development_end, holdout_start, holdout_end, set_by, reason, set_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING lock_id",
        (lock.sha256, lock.development_end, lock.holdout_start, lock.holdout_end, by, reason, now),
    ).fetchone()
    assert row is not None
    return int(row[0])


def require(conn: psycopg.Connection, path: Path | None = None) -> Lock:
    """The lock in force, or LockMismatch: nothing anchored, or the file does not match the newest row."""
    lock = from_file(path)
    row = conn.execute(
        "SELECT config_sha256 FROM research_lock ORDER BY lock_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise LockMismatch(
            "the research lock is not anchored in the database (scripts/research_lock.py anchor)"
        )
    if row[0] != lock.sha256:
        raise LockMismatch(
            "the research lock file differs from the one anchored in the database: research is refused"
        )
    return lock


class _GuardedLoaded(Loaded):
    """A Loaded whose rows already stop before the holdout; asking for a window that reaches it is an error."""

    holdout_start: date

    def history(self, start: date, end: date, **kw: Any) -> History:
        if end >= self.holdout_start:
            raise HoldoutAccess(
                f"the window ends {end}, inside the research holdout (from {self.holdout_start})"
            )
        return super().history(start, end, **kw)

    def lenient(self) -> Loaded:
        return _clip(super().lenient(), self.holdout_start)


def _clip(loaded: Loaded, holdout_start: date) -> _GuardedLoaded:
    keep = [i for i, d in enumerate(loaded.days) if d < holdout_start]
    through = loaded.through
    out = _GuardedLoaded(
        [loaded.rows[i] for i in keep],
        [r for r in loaded.recs if r.ex_date < holdout_start],
        loaded.visible_after,
        loaded.strict,
        [loaded.owners[i] for i in keep],
        None if through is None else [through[i] for i in keep],
        frozenset(d for d in loaded.vendor_dividends if d < holdout_start),
    )
    out.holdout_start = holdout_start
    return out


class ResearchReader:
    """The only price reader research code may hold. See the module doc."""

    __slots__ = ("_inner", "_memo", "_start")
    _inner: BarReader
    _memo: dict[tuple[int, ...], str | None]
    _start: date

    def __init__(self, inner: BarReader, lock: Lock) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_start", lock.holdout_start)
        object.__setattr__(self, "_memo", {})

    @property
    def known_at(self) -> datetime | None:
        return self._inner.known_at

    @property
    def visible_after(self) -> Any:
        return self._inner.visible_after

    @property
    def source(self) -> str:
        return self._inner.source

    @property
    def cutoff(self) -> date | None:
        return self._inner.cutoff

    def snapshot_hash(self, instrument_ids: list[int]) -> str | None:
        """Remembered per set of instruments: every trial of a study asks for the same ones and the hash walks all their bars."""
        key = tuple(sorted(set(instrument_ids)))
        if key not in self._memo:
            self._memo[key] = self._inner.snapshot_hash(list(key))
        return self._memo[key]

    def isin_links(self) -> list[Link]:
        return self._inner.isin_links()

    def load(self, instrument_id: int, *, strict: bool = False) -> Loaded:
        return _clip(self._inner.load(instrument_id, strict=strict), self._start)

    def issuer_load(self, instrument_id: int, *, strict: bool = False) -> Loaded:
        return _clip(self._inner.issuer_load(instrument_id, strict=strict), self._start)

    def history(self, instrument_id: int, start: date, end: date, **kw: Any) -> History:
        strict = kw.pop("strict", False)
        return self.load(instrument_id, strict=strict).history(start, end, **kw)

    def issuer_history(self, instrument_id: int, start: date, end: date, **kw: Any) -> History:
        strict = kw.pop("strict", False)
        return self.issuer_load(instrument_id, strict=strict).history(start, end, **kw)


def research_minute_history(
    conn: psycopg.Connection | None,
    lock: Lock,
    instrument_id: int,
    start: date,
    end: date,
    **kw: Any,
) -> History:
    """`minute_history` for research: refused, before any query, when the window reaches the holdout."""
    if end >= lock.holdout_start:
        raise HoldoutAccess(
            f"the window ends {end}, inside the research holdout (from {lock.holdout_start})"
        )
    assert conn is not None
    return minute_history(conn, instrument_id, start, end, **kw)
