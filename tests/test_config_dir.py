"""
A container replaces /srv with every update, so a deployment that wants to
keep its SECRET_KEY and CRYPTOGRAPHY_KEY points CMDBSYNCER_CONFIG_DIR at a
mounted directory instead. Three things have to hold for that to work, and
all of them are invisible until the day somebody upgrades:

* the directory is on the import path even while it is still empty — the
  first boot is what creates local_config.py in it, and `sys self_configure`
  has to be able to import the file it just wrote, in that same run
* `sys self_configure` writes to that directory rather than to the working
  directory it happens to be started from
* the license file is looked for next to it, so an uploaded license survives
  the upgrade as well

The real import order only exists in a fresh interpreter, so these run in a
subprocess. The working directory is deliberately a *different* scratch
directory than the config directory — with the two pointing at the same
place, a path that quietly fell back to the working directory would pass.
"""
import os
import subprocess
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(snippet, seed_local_config=None):
    """Run `snippet` with CMDBSYNCER_CONFIG_DIR set, from an unrelated cwd.

    `seed_local_config` is written into the config directory beforehand;
    without it the directory stays empty, which is the first-boot state.
    `{config_dir}` is substituted in the snippet.
    """
    with tempfile.TemporaryDirectory() as config_dir, \
            tempfile.TemporaryDirectory() as workdir:
        if seed_local_config is not None:
            with open(os.path.join(config_dir, 'local_config.py'),
                      'w', encoding='utf-8') as fh:
                fh.write(seed_local_config)
        env = dict(os.environ)
        env['PYTHONPATH'] = _REPO_ROOT
        # CLI mode keeps the import light — no Flask-Admin scaffolding, and
        # therefore no live MongoDB needed.
        env['CMDBSYNCER_CLI'] = '1'
        env['CMDBSYNCER_CONFIG_DIR'] = config_dir
        env['config'] = 'base'
        env.pop('CMDBSYNCER_LICENSE', None)
        return subprocess.run(
            [sys.executable, '-c', snippet.replace('{config_dir}', config_dir)],
            cwd=workdir, env=env, capture_output=True, text=True, check=False,
        )


class TestEmptyConfigDirIsImportable(unittest.TestCase):
    """The first boot happens before local_config.py exists anywhere."""

    def test_directory_is_on_the_path(self):
        """An empty config directory is still an import location."""
        result = _run(
            "import sys\n"
            "import application\n"
            "print('ON_PATH', '{config_dir}' in sys.path)\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ON_PATH True', result.stdout)


class TestConfigDirWins(unittest.TestCase):
    """Config belongs in the mounted directory, not in the image layer."""

    def test_self_configure_writes_to_the_config_dir(self):
        """The generated keys land in the mounted directory."""
        result = _run(
            "import os\n"
            "from application.plugins.maintenance import _local_config_path\n"
            "expected = os.path.join(os.environ['CMDBSYNCER_CONFIG_DIR'],\n"
            "                        'local_config.py')\n"
            "print('MATCHES', _local_config_path() == expected)\n"
            "print('NOT_CWD', _local_config_path() != 'local_config.py')\n",
            seed_local_config="config = {}\n",
        )
        self.assertIn('NOT_CWD True', result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('MATCHES True', result.stdout)

    def test_the_settings_are_read_from_there(self):
        """And the app reads its configuration back from the same place."""
        result = _run(
            "from application import app\n"
            "print('MARKER', app.config['MARKER'])\n",
            seed_local_config="config = {'MARKER': 'from-the-config-dir'}\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('MARKER from-the-config-dir', result.stdout)

    def test_the_license_is_looked_for_next_to_it(self):
        """An uploaded license survives the upgrade along with it."""
        result = _run(
            "from application import enterprise\n"
            "print('LICENSE', enterprise.license_path())\n",
            seed_local_config="config = {}\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        license_path = result.stdout.split('LICENSE ')[1].strip()
        self.assertTrue(license_path.endswith('/license.jwt'), license_path)
        self.assertNotEqual(os.path.dirname(license_path), os.getcwd())


if __name__ == '__main__':
    unittest.main()
