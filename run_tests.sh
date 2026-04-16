#!/usr/bin/env bash
# Run the unit-test suite, discovering tests in plugin and module directories.
# The bootstrap in tests/__init__.py must run first to stub out MongoDB.
set -euo pipefail

cd "$(dirname "$0")"
exec python run_tests.py "$@"
