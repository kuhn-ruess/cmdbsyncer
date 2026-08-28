"""Tests for the ``--override`` switch of the rule import."""
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=wrong-import-position,too-few-public-methods

import importlib.util
import json
import os
import sys
import types
import unittest

from mongoengine.errors import NotUniqueError


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Same approach as tests/test_rule_filename_detect.py: load the module
# straight from disk with a minimal rule registry, so the import logic
# can be tested without Flask/Mongo.
_defs = types.ModuleType('application.plugins.rules.rule_definitions')
_defs.rules = {
    'custom_attributes':
        ('application.plugins.rules.tests_fake_models', 'FakeRule'),
}
sys.modules['application.plugins.rules.rule_definitions'] = _defs

_MOD_PATH = os.path.join(
    REPO_ROOT, 'application', 'plugins', 'rules', 'rule_import_export.py',
)
_MODULE_NAME = 'application.plugins.rules.rule_import_export'
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = mod
_spec.loader.exec_module(mod)


class _FakeField:
    def __init__(self, unique=False, db_field=None):
        self.unique = unique
        self.db_field = db_field


class _FakeQuerySet:
    def __init__(self, store, criteria):
        self.store = store
        self.criteria = criteria

    def _matches(self, entry):
        for key, value in self.criteria.items():
            key = '_id' if key == 'id' else key
            if entry.get(key) != value:
                return False
        return True

    def delete(self):
        keep = [x for x in self.store if not self._matches(x)]
        deleted = len(self.store) - len(keep)
        self.store[:] = keep
        return deleted


class _FakeDoc:
    def __init__(self, data, store):
        self.data = data
        self.store = store

    def save(self, force_insert=False):  # pylint: disable=unused-argument
        for entry in self.store:
            if (entry.get('_id') == self.data.get('_id')
                    or entry.get('name') == self.data.get('name')):
                raise NotUniqueError('duplicate')
        self.store.append(self.data)


class FakeRule:
    """Stand-in for a MongoEngine rule document."""

    store = []
    _fields = {
        'id': _FakeField(db_field='_id'),
        'name': _FakeField(unique=True, db_field='name'),
    }

    @classmethod
    def objects(cls, **criteria):
        return _FakeQuerySet(cls.store, criteria)

    def from_json(self, raw):
        return _FakeDoc(json.loads(raw), FakeRule.store)


_models = types.ModuleType('application.plugins.rules.tests_fake_models')
_models.FakeRule = FakeRule
sys.modules['application.plugins.rules.tests_fake_models'] = _models


def _rule(oid, name, value):
    return {'_id': {'$oid': oid}, 'name': name, 'value': value}


class ImportOverrideTests(unittest.TestCase):
    def setUp(self):
        FakeRule.store = []

    def test_duplicate_is_skipped_without_override(self):
        mod.import_one_rule(_rule('a' * 24, 'rule1', 'old'), 'custom_attributes')
        status = mod.import_one_rule(_rule('a' * 24, 'rule1', 'new'),
                                     'custom_attributes')
        self.assertEqual(status, 'duplicate')
        self.assertEqual(len(FakeRule.store), 1)
        self.assertEqual(FakeRule.store[0]['value'], 'old')

    def test_override_replaces_rule_with_same_id(self):
        mod.import_one_rule(_rule('a' * 24, 'rule1', 'old'), 'custom_attributes')
        status = mod.import_one_rule(_rule('a' * 24, 'rule1', 'new'),
                                     'custom_attributes', override=True)
        self.assertEqual(status, 'imported')
        self.assertEqual(len(FakeRule.store), 1)
        self.assertEqual(FakeRule.store[0]['value'], 'new')

    def test_override_replaces_rule_with_same_name(self):
        # Same rule, exported from another instance: new id, same name.
        mod.import_one_rule(_rule('a' * 24, 'rule1', 'old'), 'custom_attributes')
        status = mod.import_one_rule(_rule('b' * 24, 'rule1', 'new'),
                                     'custom_attributes', override=True)
        self.assertEqual(status, 'imported')
        self.assertEqual(len(FakeRule.store), 1)
        self.assertEqual(FakeRule.store[0]['value'], 'new')

    def test_override_keeps_unrelated_rules(self):
        mod.import_one_rule(_rule('a' * 24, 'rule1', 'old'), 'custom_attributes')
        mod.import_one_rule(_rule('b' * 24, 'rule2', 'keep'), 'custom_attributes')
        mod.import_one_rule(_rule('a' * 24, 'rule1', 'new'),
                            'custom_attributes', override=True)
        self.assertEqual(sorted(x['name'] for x in FakeRule.store),
                         ['rule1', 'rule2'])
        self.assertEqual([x for x in FakeRule.store
                          if x['name'] == 'rule2'][0]['value'], 'keep')

    def test_import_rule_lines_counts_overridden_rules(self):
        mod.import_one_rule(_rule('a' * 24, 'rule1', 'old'), 'custom_attributes')
        lines = [
            json.dumps({'rule_type': 'custom_attributes'}),
            json.dumps(_rule('a' * 24, 'rule1', 'new')),
        ]
        counts = mod.import_rule_lines(lines, override=True)
        self.assertEqual(counts, {'custom_attributes': 1})
        self.assertEqual(FakeRule.store[0]['value'], 'new')


if __name__ == '__main__':
    unittest.main()
