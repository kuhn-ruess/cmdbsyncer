"""CMDB templates export as their own rule type, split off from hosts.

Also covers the opt-in gate of the Checkmk password store, which shares
the same skip mechanism.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring,wrong-import-position

import importlib.util
import os
import sys
import types
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeDoc:  # pylint: disable=too-few-public-methods
    def __init__(self, payload):
        self.payload = payload

    def to_json(self):
        return self.payload


class FakeHost:  # pylint: disable=too-few-public-methods
    """Stand-in for the Host model: records the filter it was queried with."""

    calls = []
    documents = [
        {'object_type': 'host', 'hostname': 'srv1'},
        {'object_type': 'template', 'hostname': 'linux-tpl'},
    ]

    @classmethod
    def objects(cls, **kwargs):
        cls.calls.append(kwargs)
        if kwargs.get('object_type') == 'template':
            wanted = [d for d in cls.documents if d['object_type'] == 'template']
        elif kwargs.get('object_type__ne') == 'template':
            wanted = [d for d in cls.documents if d['object_type'] != 'template']
        else:
            wanted = cls.documents
        return [FakeDoc(d['hostname']) for d in wanted]


# The fake Host model lives under a name of its own — shadowing the real
# ``application.models.host`` in sys.modules would leak into every other
# test in this process. The registry stub and the module under test are
# swapped in only for the load and put back afterwards; `mod` keeps its
# own reference to the stubbed registry.
class FakePassword:  # pylint: disable=too-few-public-methods
    """Stand-in for the Checkmk password store model."""

    @classmethod
    def objects(cls, **_kwargs):
        return [FakeDoc('secret-store-entry')]


_host_module = types.ModuleType('tests.fake_host_model')
_host_module.Host = FakeHost
_host_module.CheckmkPassword = FakePassword
sys.modules['tests.fake_host_model'] = _host_module

_defs = types.ModuleType('application.plugins.rules.rule_definitions')
_defs.rules = {
    'cmk_filter': ('application.plugins.checkmk.models', 'CheckmkFilterRule'),
    'host_objects': ('tests.fake_host_model', 'Host',
                     {'object_type__ne': 'template'}),
    'cmdb_templates': ('tests.fake_host_model', 'Host',
                       {'object_type': 'template'}),
    'cmk_passwords': ('tests.fake_host_model', 'CheckmkPassword'),
}

_MOD_PATH = os.path.join(
    REPO_ROOT, 'application', 'plugins', 'rules', 'rule_import_export.py',
)
_MODULE_NAME = 'application.plugins.rules.rule_import_export'
_DEFS_NAME = 'application.plugins.rules.rule_definitions'
_saved = {name: sys.modules.get(name) for name in (_MODULE_NAME, _DEFS_NAME)}
sys.modules[_DEFS_NAME] = _defs
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = mod
_spec.loader.exec_module(mod)
for _name, _original in _saved.items():
    if _original is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _original


class ExportTemplatesTests(unittest.TestCase):

    def setUp(self):
        FakeHost.calls = []

    def test_templates_only_contain_templates(self):
        self.assertEqual(list(mod.iter_rules_of_type('cmdb_templates')),
                         ['linux-tpl'])

    def test_host_objects_skip_templates(self):
        self.assertEqual(list(mod.iter_rules_of_type('host_objects')), ['srv1'])

    def test_query_uses_registry_filter(self):
        list(mod.iter_rules_of_type('host_objects'))
        self.assertEqual(FakeHost.calls, [{'object_type__ne': 'template'}])

    def test_templates_exported_without_include_hosts(self):
        exported = list(mod.iter_all_rules())
        self.assertEqual(exported, [('cmdb_templates', 'linux-tpl')])

    def test_include_hosts_adds_hosts_without_duplicating_templates(self):
        exported = list(mod.iter_all_rules(include_hosts=True))
        self.assertEqual(exported, [('cmdb_templates', 'linux-tpl'),
                                    ('host_objects', 'srv1')])

    def test_grouped_export_keeps_types_apart(self):
        grouped = mod.grouped_rules_export(include_hosts=True)['rules']
        self.assertEqual(sorted(grouped), ['cmdb_templates', 'host_objects'])

    def test_passwords_need_their_own_flag(self):
        self.assertNotIn('cmk_passwords',
                         [rule_type for rule_type, _rule in mod.iter_all_rules()])
        self.assertIn(('cmk_passwords', 'secret-store-entry'),
                      list(mod.iter_all_rules(include_passwords=True)))
