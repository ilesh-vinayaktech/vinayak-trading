"""Write a manifest of ALL membership evidence (every raw file's sha256 from the lake manifests, the
transcription files and the parser versions) and one overall digest. A result can then cite exactly
which evidence it was built from.
usage: freeze_evidence.py --lake data/lake [--out docs/evidence-manifest.json]"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from algo.data.providers.nse_index_monthly import PARSER_VERSION as MONTHLY_PARSER
from algo.data.providers.nse_index_releases import PARSER_VERSION as RELEASE_PARSER

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--out", type=Path, default=Path("docs/evidence-manifest.json"))
a = ap.parse_args()
root = a.lake / "raw" / "niftyindices"
entries = []
for mf in sorted(root.rglob("v*.manifest.json")):
    m = json.loads(mf.read_text())
    entries.append((m["dataset"], m["partition"], m["version"], m["checksum"], m["url"]))
for t in sorted(Path("config/transcriptions").glob("*.json")):
    entries.append(("transcription", t.stem, 1, hashlib.sha256(t.read_bytes()).hexdigest(), t.name))
overall = hashlib.sha256()
for e in entries:
    overall.update("|".join(map(str, e[:4])).encode() + b"\n")
by_kind = Counter(
    "press_release" if e[0].startswith("pr_") else e[0] for e in entries
)  # fmt: skip
doc = {
    "created": datetime.now(UTC).isoformat(timespec="seconds"),
    "files": len(entries),
    "by_kind": dict(sorted(by_kind.items())),
    "release_parser_version": RELEASE_PARSER,
    "monthly_parser_version": MONTHLY_PARSER,
    "overall_sha256": overall.hexdigest(),
}
a.out.write_text(json.dumps(doc, indent=1) + "\n")
Path("data/reports").mkdir(parents=True, exist_ok=True)
Path("data/reports/evidence_manifest_full.json").write_text(
    json.dumps({**doc, "entries": entries}, indent=1)
)
print(json.dumps(doc, indent=1))
