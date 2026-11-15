# ruff: noqa: E501
"""The committed hashes of the feature definitions (config/feature_manifests.json). `check` fails when code and file differ; `write` regenerates the file.
Run `write` ONLY after adding a NEW version of a feature: editing a version that already exists must never be hidden by regenerating this file.
usage: feature_manifests.py check|write"""

import json
import sys
from pathlib import Path

from algo.features.registry import golden

PATH = Path("config/feature_manifests.json")
cmd = sys.argv[1] if len(sys.argv) == 2 else ""
if cmd == "write":
    PATH.write_text(json.dumps(golden(), indent=1, sort_keys=True) + "\n")
    print("wrote", PATH)
elif cmd == "check":
    stored = json.loads(PATH.read_text())
    now = golden()
    changed = sorted(k for k in now if k in stored and stored[k] != now[k])
    print(
        "changed:",
        changed or "none",
        "| new:",
        sorted(set(now) - set(stored)) or "none",
        "| gone:",
        sorted(set(stored) - set(now)) or "none",
    )
    sys.exit(1 if changed or set(stored) != set(now) else 0)
else:
    sys.exit(__doc__)
