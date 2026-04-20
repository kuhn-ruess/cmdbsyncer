#!/usr/bin/env python3
"""
Test runner that discovers tests in tests/ and all plugin test directories.

Imports the test bootstrap first (tests/__init__.py) to stub out MongoDB
dependencies, then auto-discovers test files in:
  - tests/
  - application/plugins/*/tests/
"""
import glob
import os
import sys
import unittest

# Discovery paths below are relative — anchor to the script's directory so
# the runner works regardless of the caller's cwd.
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

# Re-exec under the project virtualenv if one exists and we're not already
# inside it, so `./run_tests.py` works without `source venv/bin/activate`.
_current_python = os.path.realpath(sys.executable)
for _venv_python in (".venv/bin/python", "venv/bin/python"):
    _venv_python = os.path.realpath(_venv_python)
    if os.path.isfile(_venv_python) and _current_python != _venv_python:
        os.execv(_venv_python, [_venv_python, __file__, *sys.argv[1:]])
    if os.path.isfile(_venv_python):
        break

import tests  # pylint: disable=unused-import,wrong-import-position  # noqa: F401,E402 — bootstrap stubs

loader = unittest.TestLoader()
suite = unittest.TestSuite()

# Core tests — use tests/ as its own top_level_dir so the bootstrapped
# `application` stub in sys.modules isn't re-shadowed by auto-discovery.
suite.addTests(loader.discover("tests", pattern="test*.py", top_level_dir="tests"))

# Plugin tests (auto-discovered) — each plugin's tests/ is its own top_level_dir
# for the same reason; otherwise unittest tries to import the test package under
# its full `application.plugins.<name>.tests` dotted path and collides with the
# stubbed `application` package.
for test_dir in sorted(glob.glob("application/plugins/*/tests")):
    suite.addTests(loader.discover(test_dir, pattern="test*.py", top_level_dir=test_dir))

runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
