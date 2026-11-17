"""
The Jinja help panel of the rule forms.

It lists the syncer's Jinja functions and filters. They are registered in
syncer_jinja, the help lives in jinja_help: a function added to one but
not the other would be missing from the panel, or the panel would offer
one that does not exist.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import sys
import types
import unittest
from unittest.mock import MagicMock

from tests.source_loader import (
    keep_modules, load_source, restore_modules, stub_account_macro,
)


class JinjaHelpTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        stub_account_macro()
        cls._stubs = keep_modules((
            'application.helpers.syncer_jinja',
            'application.helpers.jinja_help',
            'application.helpers.lookup_table',
            'application.models.lookup_table',
        ))
        load_source('application.helpers.lookup_table',
                    'application/helpers/lookup_table.py')
        cls.jinja = load_source(
            'application.helpers.syncer_jinja',
            'application/helpers/syncer_jinja.py')
        cls.help = load_source(
            'application.helpers.jinja_help',
            'application/helpers/jinja_help.py')
        cls.model = types.ModuleType('application.models.lookup_table')
        cls.lookup_table = MagicMock(name='LookupTable')
        cls.model.LookupTable = cls.lookup_table
        sys.modules['application.models.lookup_table'] = cls.model

    @classmethod
    def tearDownClass(cls):
        restore_modules(cls._stubs)

    def test_every_function_has_help(self):
        builtin = self.jinja.SandboxedEnvironment().globals
        own = self.jinja.global_names() - set(builtin)
        documented = {name for name, _snippet, _text in self.help.FUNCTIONS}
        self.assertEqual(documented, own)

    def test_every_syncer_filter_has_help(self):
        builtin = self.jinja.SandboxedEnvironment().filters
        own = set(self.jinja.JINJA_ENV.filters) - set(builtin)
        documented = {name for name, _snippet, _text in self.help.FILTERS}
        self.assertEqual(documented, own)

    def test_every_snippet_is_one_line_valid_jinja(self):
        for group in (self.help.FUNCTIONS, self.help.FILTERS,
                      self.help.BASICS, self.help.RULE_VARIABLES,
                      self.help.SETUP_RULE_VARIABLES,
                      self.help.CHECKMK_RULE_PASSWORDS,
                      self.help.DCD_RULE_VARIABLES):
            for name, snippet, _text in group:
                self.assertNotIn('\n', snippet, name)
                self.assertIsNone(self.jinja.check_jinja_syntax(snippet), name)

    def test_a_form_hands_in_its_own_variables(self):
        query = self.lookup_table.objects.only.return_value.order_by
        query.return_value = []
        names = {entry['name'] for entry in self.help.jinja_help(
            ['folder'], variables=self.help.SETUP_RULE_VARIABLES)['entries']
                 if entry['group'] == 'Variables'}
        self.assertIn('HOST_FOLDER', names)
        self.assertNotIn('FIRST_MATCHING_TAG', names)
        default = {entry['name'] for entry in self.help.jinja_help(
            ['new_value'])['entries'] if entry['group'] == 'Variables'}
        self.assertIn('FIRST_MATCHING_TAG', default)

    def test_extra_groups_follow_the_variables(self):
        query = self.lookup_table.objects.only.return_value.order_by
        query.return_value = []
        entries = self.help.jinja_help(
            ['value_template'], variables=self.help.SETUP_RULE_VARIABLES,
            extra=[('Passwords', self.help.CHECKMK_RULE_PASSWORDS)])['entries']
        groups = [entry['group'] for entry in entries]
        self.assertEqual(groups.index('Passwords'),
                         len(self.help.SETUP_RULE_VARIABLES))
        self.assertIn('host secret', {entry['name'] for entry in entries})

    def test_lookup_tables_list_their_key_and_columns(self):
        table = MagicMock(entries='location;datacenter;owner\nsite-a;DC1;team-a\n',
                          mode='key_value')
        table.name = 'datacenters'
        rows = MagicMock(entries='site;owner\nsite-a;team-a\n', mode='table')
        rows.name = 'owners'
        empty = MagicMock(entries='', mode='key_value')
        empty.name = 'empty'
        query = self.lookup_table.objects.only.return_value.order_by
        query.return_value = [table, rows, empty]
        self.assertEqual(self.help.lookup_tables(), [
            {'name': 'datacenters', 'mode': 'key_value', 'key': 'location',
             'columns': ['datacenter', 'owner']},
            {'name': 'owners', 'mode': 'table', 'key': '',
             'columns': ['site', 'owner']},
            {'name': 'empty', 'mode': 'key_value', 'key': '', 'columns': []},
        ])
