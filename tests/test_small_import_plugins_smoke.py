"""
Small import plugins: one odd record or setting must not end the import.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from unittest.mock import MagicMock, patch

from application.plugins.jira.jira import JiraOnPrem
from application.plugins.pyodbc import pyodbc as odbc
from application.plugins.yml.yml import YMLSyncer

# A group of a YML file without variables
yml = YMLSyncer.__new__(YMLSyncer)
yml.config = {'name_of_variables_key': 'vars', 'name_of_hosts_key': 'hosts'}
eq(yml.parse_yml({'with': {'hosts': ['srv1'], 'vars': {'os': 'linux'}},
                  'without': {'hosts': ['srv2']}}),
   [{'hostname': 'srv1', 'os': 'linux'}, {'hostname': 'srv2'}], 'yml groups')

# The page size of Jira comes from a custom field, so it is a string
pages = [{'data': [{'key': 1, 'identifier': 'a'}, {'key': 2, 'identifier': 'b'}]},
         {'data': [{'key': 3, 'identifier': 'c'}]}]
jira = JiraOnPrem.__new__(JiraOnPrem)
jira.config = {'page_size': '2', 'address': 'https://jira.example.com',
               'username': 'u', 'password': 'p'}
jira.inner_request = MagicMock(
    side_effect=[MagicMock(json=MagicMock(return_value=page)) for page in pages])
eq(jira._collect_meta()[0], {'environment': {1: 'a', 2: 'b', 3: 'c'}}, 'jira pages')

# One row of an ODBC source without a hostname
cursor = MagicMock(description=[('name',), ('os',)])
cursor.fetchall.return_value = [('srv1 ', 'linux'), (None, 'linux'), ('srv2', 'bsd')]
syncer = odbc.ODBC.__new__(odbc.ODBC)
syncer.log_details = []
syncer.config = {
    'name': 'odbc', 'address': '192.0.2.1', 'serverport': 1433,
    'driver': 'd', 'database': 'db', 'username': 'u', 'password': 'p',
    'fields': 'name,os', 'table': 'hosts', 'hostname_field': 'name',
}
driver = MagicMock()
driver.connect.return_value.cursor.return_value = cursor
with patch.object(odbc, 'pyodbc', driver, create=True):
    eq([hostname for hostname, _labels in syncer._innter_sql()], ['srv1', 'srv2'], 'odbc rows')

print('SMALL_IMPORTS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class SmallImportPluginTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_small_imports(self):
        """See the checks in SNIPPET."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('SMALL_IMPORTS_OK', result.stdout)
