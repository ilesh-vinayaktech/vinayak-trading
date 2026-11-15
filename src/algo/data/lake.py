"""Raw lake: append-only, versioned, checksummed. Path raw/{source}/{dataset}/dt=YYYY-MM-DD/vNNNN.*
Nothing is ever overwritten; a changed payload becomes the next version."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from algo.core.clock import require_utc

INGEST_KINDS = frozenset(
    {"initial", "provider_correction", "parser_reprocess", "manual_correction"}
)


class IntegrityError(Exception):
    pass


@dataclass(frozen=True)
class Manifest:
    source: str
    dataset: str
    partition: str
    version: int
    checksum: str
    url: str
    fetched_at: str
    ingest_kind: str
    size: int


class LocalLake:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, source: str, dataset: str, d: date) -> Path:
        return self.root / "raw" / source / dataset / f"dt={d.isoformat()}"

    def versions(self, source: str, dataset: str, d: date) -> list[Manifest]:
        files = sorted(self._dir(source, dataset, d).glob("v*.manifest.json"))
        return [Manifest(**json.loads(f.read_text())) for f in files]

    def put(
        self,
        source: str,
        dataset: str,
        d: date,
        data: bytes,
        *,
        url: str,
        fetched_at: datetime,
        ingest_kind: str = "initial",
    ) -> Manifest:
        """Store payload. Identical to latest version => return that manifest (idempotent)."""
        if ingest_kind not in INGEST_KINDS:
            raise ValueError(f"bad ingest_kind {ingest_kind}")
        checksum = hashlib.sha256(data).hexdigest()
        existing = self.versions(source, dataset, d)
        if existing and existing[-1].checksum == checksum:
            return existing[-1]
        version = len(existing) + 1
        base = self._dir(source, dataset, d)
        base.mkdir(parents=True, exist_ok=True)
        m = Manifest(
            source, dataset, d.isoformat(), version, checksum, url,
            require_utc(fetched_at).isoformat(), ingest_kind, len(data),
        )  # fmt: skip
        final = base / f"v{version:04d}.bin"
        # A version exists only once its manifest does. A crash or a full disk can leave a
        # half-written payload, so write to a temporary name, move it into place, then write the
        # manifest last; leftovers of an earlier failed attempt carry no manifest and are cleared.
        for stale in (*base.glob("*.tmp"), final):
            if not (base / f"v{version:04d}.manifest.json").exists():
                stale.unlink(missing_ok=True)
        tmp = base / f"v{version:04d}.bin.tmp"
        try:
            with open(tmp, "xb") as f:  # "x": never overwrite
                f.write(data)
            tmp.replace(final)
            manifest_tmp = base / f"v{version:04d}.manifest.json.tmp"
            manifest_tmp.write_text(json.dumps(asdict(m)))
            manifest_tmp.replace(base / f"v{version:04d}.manifest.json")
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return m

    def get(self, m: Manifest) -> bytes:
        data = (self._dir(m.source, m.dataset, date.fromisoformat(m.partition))
                / f"v{m.version:04d}.bin").read_bytes()  # fmt: skip
        if hashlib.sha256(data).hexdigest() != m.checksum:
            raise IntegrityError(f"checksum mismatch for {m.source}/{m.dataset}/{m.partition}")
        return data

    def latest(self, source: str, dataset: str) -> Manifest | None:
        """Newest version of the newest partition (partitions are ISO dates, so they sort)."""
        parts = sorted((self.root / "raw" / source / dataset).glob("dt=*"))
        for part in reversed(parts):
            vs = self.versions(source, dataset, date.fromisoformat(part.name[3:]))
            if vs:
                return vs[-1]
        return None
