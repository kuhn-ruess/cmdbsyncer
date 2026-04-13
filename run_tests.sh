#!/usr/bin/env bash
# Run the unit-test suite without triggering unittest's full-repo auto-discovery
# (which would walk into venv/, .claude/worktrees/ and application/ and fail).
set -euo pipefail

cd "$(dirname "$0")"
exec python -m unittest discover -s tests -t . "$@"
