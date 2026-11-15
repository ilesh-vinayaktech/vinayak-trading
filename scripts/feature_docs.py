# ruff: noqa: E501
"""docs/features.md from the registry. usage: feature_docs.py check|write"""

import sys
from pathlib import Path

from algo.features.docs import render

PATH = Path("docs/features.md")
if sys.argv[1:] == ["write"]:
    PATH.write_text(render())
elif sys.argv[1:] == ["check"]:
    sys.exit(0 if PATH.read_text() == render() else "docs/features.md is out of date: run feature_docs.py write")
else:
    sys.exit(__doc__)
