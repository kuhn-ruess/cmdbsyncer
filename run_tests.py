"""
Test runner that discovers tests in tests/ and all plugin test directories.

Imports the test bootstrap first (tests/__init__.py) to stub out MongoDB
dependencies, then auto-discovers test files in:
  - tests/
  - application/plugins/*/tests/
"""
import glob
import sys
import unittest

import tests  # pylint: disable=unused-import  # noqa: F401 — bootstrap stubs

loader = unittest.TestLoader()
suite = unittest.TestSuite()

# Core tests
suite.addTests(loader.discover("tests", pattern="test*.py"))

# Plugin tests (auto-discovered)
for test_dir in sorted(glob.glob("application/plugins/*/tests")):
    suite.addTests(loader.discover(test_dir, pattern="test*.py"))

runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
