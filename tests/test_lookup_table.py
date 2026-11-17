"""
Lookup Tables and the `lookup` Jinja helper.

A table maps the value of one attribute to the value another attribute
gets (location to datacenter, for example), so a long list does not need one
rule per value.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
import json
import sys
import types
import unittest
from unittest.mock import MagicMock

import jinja2

from tests.source_loader import (
    keep_modules, load_source, restore_modules, stub_account_macro,
)

_TABLE = "location;datacenter;owner\nsite-a;DC1;team-a\nsite-b;DC2;\n site-c ; DC3 ;team-c\n"


class LookupTableTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        stub_account_macro()
        cls._stubs = keep_modules((
            'application.helpers.syncer_jinja',
            'application.helpers.lookup_table',
            'application.models.lookup_table',
        ))
        cls.helper = load_source(
            'application.helpers.lookup_table',
            'application/helpers/lookup_table.py')
        cls.jinja = load_source(
            'application.helpers.syncer_jinja',
            'application/helpers/syncer_jinja.py')
        cls.model = types.ModuleType('application.models.lookup_table')
        cls.model.LookupTable = MagicMock(name='LookupTable')
        sys.modules['application.models.lookup_table'] = cls.model

    @classmethod
    def tearDownClass(cls):
        restore_modules(cls._stubs)

    def setUp(self):
        self.helper.clear_cache()
        self.tables = {'datacenters': _TABLE}
        self.modes = {}

        def objects(name):
            query = MagicMock()
            text = self.tables.get(name)
            query.only.return_value.first.return_value = (
                None if text is None else types.SimpleNamespace(
                    entries=text, mode=self.modes.get(name, 'key_value')))
            return query
        self.model.LookupTable.objects.side_effect = objects

    def render(self, template, **context):
        return self.jinja.render_jinja(template, mode='nullify', **context)

    def test_parse(self):
        columns, rows, errors = self.helper.parse_lookup_table(_TABLE)
        self.assertEqual(columns, ['location', 'datacenter', 'owner'])
        self.assertEqual(errors, [])
        self.assertEqual(rows[2], {'location': 'site-c', 'datacenter': 'DC3',
                                   'owner': 'team-c'})

    def test_key_value_refuses_duplicate_keys_and_single_columns(self):
        _columns, _rows, errors = self.helper.parse_lookup_table(
            "id;datacenter\nsite-a;a\nsite-a;b\n")
        self.assertEqual(errors, ["Keys used more than once: 'site-a'"])
        _columns, _rows, errors = self.helper.parse_lookup_table("id\nsite-a\n")
        self.assertTrue(errors)

    def test_table_mode_takes_one_column_and_repeated_values(self):
        _columns, rows, errors = self.helper.parse_lookup_table(
            "id;datacenter\nsite-a;a\nsite-a;b\n", 'table')
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 2)
        self.tables['sites'] = "site\nsite-a\n site-b \nsite-a\n"
        self.modes['sites'] = 'table'
        self.assertEqual(self.helper.lookup_rows('sites'),
                         [{'site': 'site-a'}, {'site': 'site-b'}, {'site': 'site-a'}])
        self.assertEqual(self.render(
            "{% for row in lookup_rows('sites') %}{{ row.site }},{% endfor %}"),
            'site-a,site-b,site-a,')

    def test_lookup_in_table_mode_takes_the_first_line(self):
        self.tables['owners'] = "site;owner\nsite-a;team-a\nsite-a;team-b\n"
        self.modes['owners'] = 'table'
        self.assertEqual(self.helper.lookup('owners', 'site-a'), 'team-a')

    def test_long_table(self):
        text = "id;datacenter\n" + "".join(f"site-{i};DC{i}\n" for i in range(50000))
        _columns, rows, errors = self.helper.parse_lookup_table(text)
        self.assertEqual(errors, [])
        self.assertEqual(rows[-1]['datacenter'], 'DC49999')

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

    def test_lookup_rows(self):
        rows = self.helper.lookup_rows('datacenters')
        self.assertEqual([row['location'] for row in rows], ['site-a', 'site-b', 'site-c'])
        self.assertEqual(rows[2], {'location': 'site-c', 'datacenter': 'DC3',
                                   'owner': 'team-c'})
        self.assertEqual(self.helper.lookup_rows('missing'), [])
        # A changed row must not reach the cached table.
        rows[0]['datacenter'] = 'changed'
        self.assertEqual(self.helper.lookup('datacenters', 'site-a'), 'DC1')

    def test_lookup_rows_builds_a_json_body(self):
        template = ('{"sites": [{% for row in lookup_rows("datacenters") %}'
                    '{"name": {{ row.location | tojson }}, "dc": {{ row.datacenter | tojson }}}'
                    '{% if not loop.last %},{% endif %}{% endfor %}]}')
        body = self.jinja.render_jinja(template, mode='raise', replace_newlines=False)
        self.assertEqual(json.loads(body), {'sites': [
            {'name': 'site-a', 'dc': 'DC1'},
            {'name': 'site-b', 'dc': 'DC2'},
            {'name': 'site-c', 'dc': 'DC3'},
        ]})
        body = self.jinja.render_jinja('{{ lookup_rows("datacenters") | tojson }}',
                                       mode='raise')
        self.assertEqual(len(json.loads(body)), 3)


if __name__ == '__main__':
    unittest.main()
