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
import re
import subprocess
import sys
import time
import unittest

# Discovery paths below are relative — anchor to the script's directory so
# the runner works regardless of the caller's cwd.
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

# Re-exec under the project virtualenv if one exists and we're not already
# inside it, so `./run_tests.py` works without `source venv/bin/activate`.
# The venv is told by sys.prefix: its python is usually a symlink to the very
# interpreter that started us, and resolved it would run without the venv.
# The variable stops a venv that does not take effect from looping forever.
for _venv in (".venv", "venv"):
    _venv_python = os.path.abspath(os.path.join(_venv, "bin", "python"))
    if not os.path.isfile(_venv_python):
        continue
    if (os.path.realpath(sys.prefix) != os.path.realpath(_venv)
            and "CMDBSYNCER_TESTS_REEXEC" not in os.environ):
        os.environ["CMDBSYNCER_TESTS_REEXEC"] = "1"
        os.execv(_venv_python, [_venv_python, __file__, *sys.argv[1:]])
    break

import tests  # pylint: disable=unused-import,wrong-import-position  # noqa: F401,E402 — bootstrap stubs


def _test_files():
    """Every test file: tests/ and the tests/ of each plugin"""
    return sorted(glob.glob("tests/test*.py")
                  + glob.glob("application/plugins/*/tests/test*.py"))


def _suite(files):
    """
    The tests of the files. Each test directory is its own top_level_dir,
    so the bootstrapped `application` stub in sys.modules isn't shadowed
    by auto-discovery, and the plugin tests are not imported under their
    `application.plugins.<name>.tests` path, which would collide with it.
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for path in files:
        test_dir = os.path.dirname(path)
        suite.addTests(loader.discover(test_dir, pattern=os.path.basename(path),
                                       top_level_dir=test_dir))
    return suite


def _run(files):
    """Run the tests of the files in this process"""
    result = unittest.TextTestRunner(verbosity=2).run(_suite(files))
    return 0 if result.wasSuccessful() else 1


def _buckets(files, jobs):
    """Spread the files over the jobs, the largest first, by size"""
    buckets = [[0, []] for _ in range(jobs)]
    for path in sorted(files, key=os.path.getsize, reverse=True):
        bucket = min(buckets, key=lambda entry: entry[0])
        bucket[0] += os.path.getsize(path)
        bucket[1].append(path)
    return [entry[1] for entry in buckets if entry[1]]


def _run_parallel(files, jobs):
    """
    Run the files in parallel processes. Each one gets its own interpreter,
    the stubs of tests/__init__.py live in sys.modules. The output of a
    process is only shown when it failed.
    """
    started = time.monotonic()
    # Started all at once and waited for below, a with block per process
    # would run them one after the other
    processes = [
        (subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, __file__, "--files", *bucket],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True), bucket)
        for bucket in _buckets(files, jobs)
    ]
    failed = False
    count = 0
    for process, bucket in processes:
        output, _ = process.communicate()
        count += sum(int(x) for x in re.findall(r"^Ran (\d+) test", output, re.M))
        if process.returncode:
            failed = True
            print(output)
            print(f"FAILED in: {', '.join(bucket)}")
    print(f"Ran {count} tests in {time.monotonic() - started:.1f}s "
          f"with {len(processes)} processes")
    print("FAILED" if failed else "OK")
    return 1 if failed else 0


def main():
    """
    ./run_tests.py               all tests, in parallel processes
    ./run_tests.py --serial      all tests in this process
    ./run_tests.py FILE...       only these test files
    CMDBSYNCER_TEST_JOBS=N sets the number of processes.
    """
    args = sys.argv[1:]
    if args[:1] == ["--files"]:
        return _run(args[1:])
    files = [x for x in args if not x.startswith("--")] or _test_files()
    jobs = int(os.environ.get("CMDBSYNCER_TEST_JOBS") or os.cpu_count() or 1)
    if "--serial" in args or jobs < 2 or len(files) < 2:
        return _run(files)
    return _run_parallel(files, jobs)


sys.exit(main())
