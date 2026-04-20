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


if __name__ == '__main__':
    unittest.main()
