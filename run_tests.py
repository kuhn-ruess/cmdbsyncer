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
