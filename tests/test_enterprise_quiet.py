"""
The enterprise add-on ships inside the published Docker image, so it is
installed on every deployment — including all the ones that never bought a
license. Those must start exactly like a deployment without the package:
nothing printed, nothing logged, no License entry in the menu.

A license that is *there* and broken is the opposite case and has to stay
loud, because somebody paid for features that are not running.
"""
import importlib.util
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fresh_enterprise_module():
    """Load application/enterprise.py under a private name.

    The module keeps its load state in globals, and every test here starts
    from "nothing loaded yet" — a fresh module object is cheaper and clearer
    than resetting them by hand.
    """
    path = os.path.join(_REPO_ROOT, 'application', 'enterprise.py')
    spec = importlib.util.spec_from_file_location('_enterprise_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEnterpriseQuietWithoutLicense(unittest.TestCase):
    """load_package() behaviour with the package installed but unlicensed."""

    def setUp(self):
        self.enterprise = _fresh_enterprise_module()
        self._saved_env = os.environ.get('CMDBSYNCER_LICENSE')
        # The report is suppressed for CLI invocations; these tests are about
        # the web/worker path, where it would otherwise be printed.
        self._saved_cli = os.environ.pop('CMDBSYNCER_CLI', None)
        self.addCleanup(self._restore_cli)
        # Closed by addCleanup rather than a `with` block — it has to stay
        # alive for the whole test, not just this method.
        self._tmp = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._restore_env)

        # A stand-in for the installed add-on: importable, and raising the
        # way the real one raises when it cannot verify a license.
        pkg_dir = os.path.join(self._tmp.name, 'site-packages')
        os.makedirs(pkg_dir)
        with open(os.path.join(pkg_dir, 'cmdbsyncer_enterprise.py'),
                  'w', encoding='utf-8') as fh:
            fh.write("raise ImportError('Enterprise license not found')\n")
        sys.path.insert(0, pkg_dir)
        self.addCleanup(sys.path.remove, pkg_dir)
        self.addCleanup(sys.modules.pop, 'cmdbsyncer_enterprise', None)
        importlib.invalidate_caches()

    def _restore_env(self):
        if self._saved_env is None:
            os.environ.pop('CMDBSYNCER_LICENSE', None)
        else:
            os.environ['CMDBSYNCER_LICENSE'] = self._saved_env

    def _restore_cli(self):
        if self._saved_cli is not None:
            os.environ['CMDBSYNCER_CLI'] = self._saved_cli

    def _pending_report(self):
        """The message held back for the log pipeline, or None."""
        return getattr(self.enterprise, '_pending_report')

    def test_no_license_reports_nothing(self):
        """Community Edition: no banner on stdout, stderr or in the log."""
        os.environ['CMDBSYNCER_LICENSE'] = os.path.join(self._tmp.name, 'absent.jwt')

        self.enterprise.load_package()

        self.assertEqual(self.enterprise.load_status, 'inactive: no license installed')
        self.assertIsNone(self._pending_report())

    def test_broken_license_still_reports(self):
        """A license that is there but does not work stays loud."""
        license_path = os.path.join(self._tmp.name, 'license.jwt')
        with open(license_path, 'w', encoding='utf-8') as fh:
            fh.write('not-a-jwt')
        os.environ['CMDBSYNCER_LICENSE'] = license_path

        self.enterprise.load_package()

        self.assertTrue(self.enterprise.load_status.startswith('failed:'))
        self.assertIn('failed to activate', self._pending_report())

    def test_no_features_registered_either_way(self):
        """Neither case may leave a feature behind in the registry."""
        os.environ['CMDBSYNCER_LICENSE'] = os.path.join(self._tmp.name, 'absent.jwt')

        self.enterprise.load_package()

        self.assertFalse(self.enterprise.has_feature('audit_log'))
        self.assertIsNone(self.enterprise.run_hook('configure_logging'))


class TestLicensePathResolution(unittest.TestCase):
    """license_path() mirrors what the add-on itself reads."""

    def setUp(self):
        self.enterprise = _fresh_enterprise_module()
        self._saved_env = os.environ.get('CMDBSYNCER_LICENSE')
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._saved_env is None:
            os.environ.pop('CMDBSYNCER_LICENSE', None)
        else:
            os.environ['CMDBSYNCER_LICENSE'] = self._saved_env

    def test_environment_variable_wins(self):
        """An explicitly configured path is used as given."""
        os.environ['CMDBSYNCER_LICENSE'] = '/somewhere/else/company.jwt'
        self.assertEqual(self.enterprise.license_path(), '/somewhere/else/company.jwt')

    def test_falls_back_next_to_local_config(self):
        """Without the variable, the license sits next to local_config.py."""
        os.environ.pop('CMDBSYNCER_LICENSE', None)
        path = self.enterprise.license_path()
        # The repo root holds a local_config.py, so the fallback resolves.
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith('license.jwt'))

    def test_present_only_when_the_file_exists(self):
        """A path alone is not a license — the file has to be there."""
        with tempfile.TemporaryDirectory() as tmp:
            license_path = os.path.join(tmp, 'license.jwt')
            os.environ['CMDBSYNCER_LICENSE'] = license_path
            self.assertFalse(self.enterprise.license_file_present())
            with open(license_path, 'w', encoding='utf-8') as fh:
                fh.write('token')
            self.assertTrue(self.enterprise.license_file_present())


if __name__ == '__main__':
    unittest.main()
