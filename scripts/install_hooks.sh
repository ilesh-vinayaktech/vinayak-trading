#!/bin/sh
# Turn on the tracked git hooks in .githooks (secret scan + ruff on staged Python files). Undo: git config --unset core.hooksPath
set -e
git config core.hooksPath .githooks
echo "hooks enabled: $(git config core.hooksPath)"
