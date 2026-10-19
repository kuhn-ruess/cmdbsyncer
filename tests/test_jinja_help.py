"""
The Jinja help panel of the rule forms.

It lists the syncer's Jinja functions and filters. They are registered in
syncer_jinja, the help lives in jinja_help: a function added to one but
not the other would be missing from the panel, or the panel would offer
one that does not exist.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


class JinjaHelpTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        get_acc = sys.modules['application.helpers.get_account']
        if not hasattr(get_acc, 'get_account_variable'):
            get_acc.get_account_variable = lambda macro: None
        cls._stubs = {name: sys.modules.get(name) for name in (
            'application.helpers.syncer_jinja',
            'application.helpers.jinja_help',
            'application.models.lookup_table',
        )}
        cls.jinja = _load_source(
            'application.helpers.syncer_jinja',
            os.path.join('application', 'helpers', 'syncer_jinja.py'))
        cls.help = _load_source(
            'application.helpers.jinja_help',
            os.path.join('application', 'helpers', 'jinja_help.py'))
        cls.model = types.ModuleType('application.models.lookup_table')
        cls.lookup_table = MagicMock(name='LookupTable')
        cls.model.LookupTable = cls.lookup_table
        sys.modules['application.models.lookup_table'] = cls.model

    @classmethod
    def tearDownClass(cls):
        for name, module in cls._stubs.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

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
                      self.help.SETUP_RULE_VARIABLES):
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

    def test_lookup_tables_list_their_key_and_columns(self):
        table = MagicMock(entries='location;datacenter;owner\nsite-a;DC1;team-a\n')
        table.name = 'datacenters'
        empty = MagicMock(entries='')
        empty.name = 'empty'
        query = self.lookup_table.objects.only.return_value.order_by
        query.return_value = [table, empty]
        self.assertEqual(self.help.lookup_tables(), [
            {'name': 'datacenters', 'key': 'location',
             'columns': ['datacenter', 'owner']},
            {'name': 'empty', 'key': '', 'columns': []},
        ])
