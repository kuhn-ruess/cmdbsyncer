"""
./run_tests.py has to switch into the project venv, also when the python of
the venv is a symlink to the interpreter that started the script.

Runs a copy of the script next to a real venv and a tests package that only
reports which environment it was imported in.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RunTestsVenvTest(unittest.TestCase):

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(temp_dir.cleanup)
        self.root = os.path.realpath(temp_dir.name)
        shutil.copy(os.path.join(REPO_ROOT, 'run_tests.py'), self.root)
        os.mkdir(os.path.join(self.root, 'tests'))
        with open(os.path.join(self.root, 'tests', '__init__.py'), 'w',
                  encoding='utf-8') as handle:
            handle.write('import sys\nprint("PREFIX=" + sys.prefix)\n')

    def run_script(self):
        env = {key: value for key, value in os.environ.items()
               if key != 'CMDBSYNCER_TESTS_REEXEC'}
        result = subprocess.run(
            [sys.executable, os.path.join(self.root, 'run_tests.py')],
            env=env, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        prefix = result.stdout.split('PREFIX=')[1].splitlines()[0]
        return os.path.realpath(prefix)

    def test_switches_into_a_symlinked_venv(self):
        venv_dir = os.path.join(self.root, '.venv')
        venv.create(venv_dir, with_pip=False, symlinks=True)
        self.assertEqual(self.run_script(), venv_dir)

    def test_a_venv_without_effect_does_not_loop(self):
        bin_dir = os.path.join(self.root, '.venv', 'bin')
        os.makedirs(bin_dir)
        os.symlink(sys.executable, os.path.join(bin_dir, 'python'))
        self.assertNotEqual(self.run_script(), os.path.join(self.root, '.venv'))


if __name__ == '__main__':
    unittest.main()
