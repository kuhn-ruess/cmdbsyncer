"""
Lookup Tables and the `lookup` Jinja helper.

A table maps the value of one attribute to the value another attribute
gets (location to datacenter, for example), so a long list does not need one
rule per value.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

import jinja2


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_TABLE = "location;datacenter;owner\nsite-a;DC1;team-a\nsite-b;DC2;\n site-c ; DC3 ;team-c\n"


def _load_source(module_name, relative_path):
    """Load a source file as `module_name`, ensuring its parent exists."""
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


class LookupTableTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        get_acc = sys.modules['application.helpers.get_account']
        if not hasattr(get_acc, 'get_account_variable'):
            get_acc.get_account_variable = lambda macro: None
        cls._stubs = {name: sys.modules.get(name) for name in (
            'application.helpers.syncer_jinja',
            'application.helpers.lookup_table',
            'application.models.lookup_table',
        )}
        cls.helper = _load_source(
            'application.helpers.lookup_table',
            os.path.join('application', 'helpers', 'lookup_table.py'))
        cls.jinja = _load_source(
            'application.helpers.syncer_jinja',
            os.path.join('application', 'helpers', 'syncer_jinja.py'))
        cls.model = types.ModuleType('application.models.lookup_table')
        cls.model.LookupTable = MagicMock(name='LookupTable')
        sys.modules['application.models.lookup_table'] = cls.model

    @classmethod
    def tearDownClass(cls):
        for name, module in cls._stubs.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def setUp(self):
        self.helper.clear_cache()
        self.tables = {'datacenters': _TABLE}

        def objects(name):
            query = MagicMock()
            text = self.tables.get(name)
            query.only.return_value.first.return_value = (
                None if text is None else types.SimpleNamespace(entries=text))
            return query
        self.model.LookupTable.objects.side_effect = objects

    def render(self, template, **context):
        return self.jinja.render_jinja(template, mode='nullify', **context)

    def test_parse(self):
        columns, table, errors = self.helper.parse_lookup_table(_TABLE)
        self.assertEqual(columns, ['location', 'datacenter', 'owner'])
        self.assertEqual(errors, [])
        self.assertEqual(table['site-c'], {'location': 'site-c', 'datacenter': 'DC3',
                                         'owner': 'team-c'})

    def test_parse_refuses_duplicate_keys_and_single_columns(self):
        _columns, _table, errors = self.helper.parse_lookup_table(
            "id;datacenter\nsite-a;a\nsite-a;b\n")
        self.assertEqual(errors, ["Keys used more than once: 'site-a'"])
        _columns, _table, errors = self.helper.parse_lookup_table("id\nsite-a\n")
        self.assertTrue(errors)

    def test_long_table(self):
        text = "id;datacenter\n" + "".join(f"site-{i};DC{i}\n" for i in range(50000))
        _columns, table, errors = self.helper.parse_lookup_table(text)
        self.assertEqual(errors, [])
        self.assertEqual(table['site-49999']['datacenter'], 'DC49999')

    def test_lookup_second_column_by_default(self):
        self.assertEqual(self.helper.lookup('datacenters', 'site-a'), 'DC1')
        self.assertEqual(self.helper.lookup('datacenters', ' site-c '), 'DC3')

    def test_lookup_named_column(self):
        self.assertEqual(self.helper.lookup('datacenters', 'site-a', 'owner'), 'team-a')

    def test_lookup_falls_back_to_default(self):
        lookup = self.helper.lookup
        self.assertEqual(lookup('datacenters', 'site-x'), '')
        self.assertEqual(lookup('datacenters', 'site-x', default='none'), 'none')
        self.assertEqual(lookup('datacenters', 'site-b', 'owner', 'none'), 'none')
        self.assertEqual(lookup('datacenters', 'site-a', 'nope', 'none'), 'none')
        self.assertEqual(lookup('missing', 'site-a', default='none'), 'none')
        self.assertEqual(lookup('datacenters', None, default='none'), 'none')
        self.assertEqual(lookup('datacenters', jinja2.Undefined(name='x'),
                                default='none'), 'none')

    def test_table_is_cached_until_cleared(self):
        self.assertEqual(self.helper.lookup('datacenters', 'site-a'), 'DC1')
        self.tables['datacenters'] = "id;datacenter\nsite-a;DC9\n"
        self.assertEqual(self.helper.lookup('datacenters', 'site-a'), 'DC1')
        self.helper.clear_cache()
        self.assertEqual(self.helper.lookup('datacenters', 'site-a'), 'DC9')

    def test_in_a_template(self):
        template = ("{% if datacenter == 'unknown' %}{{ lookup('datacenters', location) }}"
                    "{% else %}{{ datacenter }}{% endif %}")
        self.assertEqual(self.render(template, datacenter='unknown', location='site-b'),
                         'DC2')
        self.assertEqual(self.render(template, datacenter='DC7', location='site-b'),
                         'DC7')
        # A host without the key attribute gets the default, it does not
        # nullify the whole value.
        self.assertEqual(self.render(
            "{{ lookup('datacenters', location, default='none') }}"), 'none')


if __name__ == '__main__':
    unittest.main()
