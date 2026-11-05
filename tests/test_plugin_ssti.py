"""
Regression tests for SSTI/RCE fixes in plugin Jinja usage.

Pentest finding 2026-04-20: several plugin modules rendered user-editable
template strings with the unsandboxed `jinja2.Template(...)`, letting any
user with the corresponding role execute arbitrary code via payloads like
`{{ cycler.__init__.__globals__.os.popen("id").read() }}`. All affected
sites must now use `jinja2.sandbox.SandboxedEnvironment`.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

from jinja2.exceptions import SecurityError


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RCE_PAYLOAD = '{{ cycler.__init__.__globals__.os.popen("id").read() }}'


def _load_source(module_name, relative_path):
    """Load a source file as `module_name`, ensuring its parent package exists."""
    parent = module_name.rsplit('.', 1)[0]
    if parent and parent not in sys.modules:
        sys.modules[parent] = types.ModuleType(parent)
        sys.modules[parent].__path__ = []  # mark as package
    path = os.path.join(_REPO_ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class IdoitRulesSandboxTest(unittest.TestCase):
    """application/plugins/idoit/rules.py must sandbox rule param rendering."""

    @classmethod
    def setUpClass(cls):
        # tests/__init__.py stubs render_jinja with a MagicMock. For this
        # regression test we need the real sandboxed implementation, so load
        # the real syncer_jinja module, patching in the missing helper.
        get_acc = sys.modules['application.helpers.get_account']
        if not hasattr(get_acc, 'get_account_variable'):
            get_acc.get_account_variable = MagicMock(name='stub.get_account_variable')
        _load_source(
            'application.helpers.syncer_jinja',
            os.path.join('application', 'helpers', 'syncer_jinja.py'),
        )
        cls.module = _load_source(
            'application.plugins.idoit.rules',
            os.path.join('application', 'plugins', 'idoit', 'rules.py'),
        )

    def _make_rule(self):
        rule = self.module.IdoitVariableRule()
        rule.attributes = {}
        rule.db_host = MagicMock(hostname='x')
        return rule

    def test_id_object_description_rejects_rce_payload(self):
        rule = self._make_rule()
        outcomes = {}
        with self.assertRaises(SecurityError):
            rule.add_outcomes(
                None,
                [{'action': 'id_object_description', 'param': _RCE_PAYLOAD}],
                outcomes,
            )

    def test_id_category_rejects_rce_payload(self):
        rule = self._make_rule()
        outcomes = {}
        with self.assertRaises(SecurityError):
            rule.add_outcomes(
                None,
                [{'action': 'id_category', 'param': _RCE_PAYLOAD}],
                outcomes,
            )

    def test_benign_template_still_renders(self):
        # Sandboxing must not break ordinary templates.
        rule = self._make_rule()
        rule.db_host = MagicMock(hostname='web01')
        outcomes = {}
        rule.add_outcomes(
            None,
            [{'action': 'id_object_description', 'param': 'host-{{ HOSTNAME }}'}],
            outcomes,
        )
        self.assertEqual(outcomes['description'], 'host-web01')


class CheckmkSiteSyncerSandboxTest(unittest.TestCase):
    """application/plugins/ansible/site_syncer.py must sandbox filename rendering."""

    @classmethod
    def setUpClass(cls):
        # Ensure the real syncer_jinja is loaded (IdoitRulesSandboxTest also
        # loads it, but don't rely on class ordering).
        get_acc = sys.modules['application.helpers.get_account']
        if not hasattr(get_acc, 'get_account_variable'):
            get_acc.get_account_variable = MagicMock(name='stub.get_account_variable')
        if not hasattr(sys.modules.get('application.helpers.syncer_jinja'), 'JINJA_ENV'):
            _load_source(
                'application.helpers.syncer_jinja',
                os.path.join('application', 'helpers', 'syncer_jinja.py'),
            )
        cls.module = _load_source(
            'application.plugins.ansible.site_syncer',
            os.path.join('application', 'plugins', 'ansible', 'site_syncer.py'),
        )

    @staticmethod
    def _make_site(filename_template):
        site = MagicMock()
        site.settings_master.cmk_version_filename = filename_template
        site.settings_master.cmk_version = '2.3.0'
        site.settings_master.cmk_edition = 'cre'
        site.settings_master.server_user = None
        site.custom_ansible_variables = []
        return site

    def test_version_filename_rejects_rce_payload(self):
        syncer = self.module.SyncSites.__new__(self.module.SyncSites)
        site = self._make_site(_RCE_PAYLOAD)
        with self.assertRaises(SecurityError):
            syncer.get_site_data(site)

    def test_version_filename_benign_template_renders(self):
        syncer = self.module.SyncSites.__new__(self.module.SyncSites)
        site = self._make_site('check-mk-{{ CMK_EDITION }}-{{ CMK_VERSION }}.deb')
        inventory = syncer.get_site_data(site)
        self.assertEqual(
            inventory['cmk_version_filename'],
            'check-mk-cre-2.3.0.deb',
        )

    def test_download_proxy_is_rendered_and_optional(self):
        syncer = self.module.SyncSites.__new__(self.module.SyncSites)
        site = self._make_site('check-mk.deb')
        site.settings_master.download_proxy = 'http://{{ "proxy" }}.example.com:3128'
        self.assertEqual(syncer.get_site_data(site)['download_proxy'],
                         'http://proxy.example.com:3128')
        site.settings_master.download_proxy = None
        self.assertEqual(syncer.get_site_data(site)['download_proxy'], '')


class JinjaGlobalsTest(unittest.TestCase):
    """Template globals must not hand out modules: up to Python 3.11
    ``datetime.sys`` led out of the sandbox."""

    @classmethod
    def setUpClass(cls):
        cls.jinja = _load_source('application.helpers.syncer_jinja',
                                 'application/helpers/syncer_jinja.py')

    def test_no_module_among_the_globals(self):
        modules = [name for name, value in self.jinja._GLOBALS.items()  # pylint: disable=protected-access
                   if isinstance(value, types.ModuleType)]
        self.assertEqual(modules, [])

    def test_datetime_has_no_way_to_other_modules(self):
        self.assertEqual(self.jinja.render_jinja("{{ datetime.sys }}"), '')

    def test_documented_datetime_spellings_still_render(self):
        for template, expected in (
            ("{{ datetime.datetime(2026, 1, 2).strftime('%Y-%m-%d') }}", '2026-01-02'),
            ("{{ (datetime.datetime(2026, 1, 3) - datetime.timedelta(days=1)).day }}", '2'),
            ("{{ datetime.datetime.now(datetime.timezone.utc).tzname() }}", 'UTC'),
            ("{{ datetime.date(2026, 1, 2).year }}", '2026'),
            ("{{ 'yes' if datetime.datetime.utcnow().year > 2000 }}", 'yes'),
        ):
            with self.subTest(template=template):
                self.assertEqual(self.jinja.render_jinja(template), expected)


if __name__ == '__main__':
    unittest.main()
