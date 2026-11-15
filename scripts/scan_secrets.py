"""Exit 1 (file:line, never the secret) if a git-tracked file looks like it holds a secret."""

import sys
from pathlib import Path

from algo.core import secret_scan

root = Path.cwd()
found = secret_scan.scan_files(root, secret_scan.tracked(root))
for f in found:
    print(f.show())
sys.exit(1 if found else 0)
