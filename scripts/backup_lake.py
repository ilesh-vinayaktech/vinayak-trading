# ruff: noqa: E501
"""Mirror the raw lake to the directory named by ALGO_LAKE_BACKUP_DIR (a second disk or a mounted share: the choice of destination is the owner's).
Rules: files are only ever ADDED at the destination (never deleted, so a file removed from the lake survives in the backup); the lake is write-once, so a
source file whose content differs from the backed-up copy is an error and is NOT copied over it; every copied file is verified by size and sha256.
Exit 1 on any problem, which the job runner turns into an alert. usage: backup_lake.py [--lake data/lake]"""

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
a = ap.parse_args()
dest_env = os.environ.get("ALGO_LAKE_BACKUP_DIR")
if not dest_env:
    sys.exit("refused: ALGO_LAKE_BACKUP_DIR is not set, so the lake has nowhere to be backed up to")
if not a.lake.is_dir():
    sys.exit(f"error: no lake at {a.lake}")
dest = Path(dest_env)
dest.mkdir(parents=True, exist_ok=True)


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


new = same = 0
differ: list[str] = []
for src in sorted(p for p in a.lake.rglob("*") if p.is_file()):
    rel = src.relative_to(a.lake)
    target = dest / rel
    if target.exists():
        if target.stat().st_size == src.stat().st_size and sha(target) == sha(src):
            same += 1
        else:
            differ.append(str(rel))
        continue
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    shutil.copy2(src, tmp)
    if sha(tmp) != sha(src):
        tmp.unlink()
        differ.append(f"{rel} (copy did not verify)")
        continue
    tmp.rename(target)
    new += 1
print(
    f"lake {a.lake} -> {dest}: {new + same} file(s) in the backup, {new} new, {len(differ)} problem(s)"
)
for d in differ:
    print(
        f"  {d} differs from the backup: the lake is write-once, investigate before anything is overwritten"
    )
sys.exit(1 if differ else 0)
