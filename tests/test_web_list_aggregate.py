"""
Aggregate by column of a rule with a pasted list: rows sharing a value become
one row, the other columns lists. Walked through with the case it exists for,
one Checkmk HTTP check per host out of a list with one line per domain.

Runs against the real app like ``tests/test_web_requests_smoke.py``, see
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


LIST_AGGREGATE = LOGIN + r'''
from unittest.mock import patch

from application.modules.rule.list_source import aggregate_rows, parse_list_source
from application.plugins.checkmk.cmk2 import CMK2
from application.plugins.checkmk.cmk_rules import CheckmkRuleSync
from application.plugins.checkmk.models import CheckmkRuleMngmt

LIST = "Host Name;domain;port\nsrv01;a.example.com;443\nsrv02;c.example.com;\nsrv01;b.example.com;8443\n"
VALUE = ("{'endpoints': [{% for name in domain %}{'url': 'https://{{ name }}'}, "
         "{% endfor %}]}")

# Rows are joined in order of first appearance, the lists stay aligned
parsed = aggregate_rows(parse_list_source(LIST), 'Host Name')
eq(parsed.rows, [
    {'host_name': 'srv01', 'domain': ['a.example.com', 'b.example.com'],
     'port': ['443', '8443']},
    {'host_name': 'srv02', 'domain': ['c.example.com'], 'port': ['']},
], 'aggregated rows')
eq(aggregate_rows(parse_list_source(LIST), '').rows, parse_list_source(LIST).rows,
   'rows without a column')
if not aggregate_rows(parse_list_source(LIST), 'nope').errors:
    fail('an unknown column is not reported')

# The form offers the field, the preview shows the joined rows
url = '/admin/checkmkrulemngmt/new/'
form = check(url, 200).get_data(as_text=True)
if not re.search(r'<input[^>]*id="list_aggregate_by"', form):
    fail('the form does not offer the column as a single line')
preview = check('/admin/checkmkrulemngmt/_list_source_preview', 200, method='post',
                headers={'X-CSRFToken': csrf(url)},
                data={'list_source': LIST, 'list_aggregate_by': 'host_name'}).get_json()
eq((preview['row_count'], preview['rows'][1]['domain'], preview['errors']),
   (2, ['c.example.com'], []), 'preview')

# An unknown column can not be saved
fields = {
    'name': 'httpv2', 'condition_typ': 'anyway', 'rule_source': 'list',
    'list_source': LIST, 'list_aggregate_by': 'nope',
    'outcomes-0-ruleset': 'active_checks:httpv2', 'outcomes-0-folder': '/',
    'outcomes-0-value_template': VALUE,
    'outcomes-0-condition_host': '{{ host_name }}',
}
check(url, 200, method='post', data={**fields, 'csrf_token': csrf(url)})
eq(CheckmkRuleMngmt.objects.count(), 0, 'rules saved with an unknown column')

# Saved through the form, the export renders one rule per host
fields['list_aggregate_by'] = 'host_name'
check(url, 302, method='post', data={**fields, 'csrf_token': csrf(url)})
rule = CheckmkRuleMngmt.objects.get(name='httpv2')
eq(rule.list_aggregate_by, 'host_name', 'stored column')

with patch.object(CMK2, '__init__', lambda self, *_a, **_k: None):
    sync = CheckmkRuleSync()
sync.account_name, sync.account_id, sync.project = 'cmk', 'cmk-id', None
sync.checkmk_version, sync.config = '2.3.0', {}
sync.log_details, sync.dry_run, sync.dry_run_plan = [], False, []
sync.debug = False
sync.rulsets_by_type = {}
sync.drop_unsupported_conditions = lambda *_a: None
sync.static_rules = [rule]
sync.calculate_static_rules()
built = {
    entry['condition']['host_name']['match_on'][0]: entry['value']
    for entry in sync.rulsets_by_type['active_checks:httpv2']
}
eq(sorted(built), ['srv01', 'srv02'], 'hosts of the rules')
for name in ('a.example.com', 'b.example.com'):
    if f'https://{name}' not in built['srv01']:
        fail(f'{name} is missing in the rule of srv01: {built["srv01"]}')
if 'c.example.com' in built['srv01'] or 'a.example.com' in built['srv02']:
    fail('domains ended up in the rule of another host')
print('LIST_AGGREGATE_OK')
'''

NAMED_OBJECTS = LOGIN + r'''
from types import SimpleNamespace

from application.modules.rule.list_source import parse_rule_list, row_name

rule = SimpleNamespace(list_source="hostname;room\nsrv01;R1\nsrv01;R2\n",
                       list_aggregate_by='hostname')
eq(row_name(parse_rule_list(rule).rows[0]), 'srv01', 'name of a joined row')
rule.list_aggregate_by = 'room'
eq(row_name(parse_rule_list(rule).rows[0]), None, 'a list names no object')
print('NAMED_OBJECTS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestWebListAggregate(unittest.TestCase):
    """Joining the rows of a pasted list by a column."""

    def _run(self, snippet, marker):
        result = run_against_app(snippet, 'False')
        self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")
        self.assertIn(marker, result.stdout)

    def test_one_rule_per_host_out_of_one_line_per_domain(self):
        """Parser, form, preview and export of a Setup Rule."""
        self._run(LIST_AGGREGATE, 'LIST_AGGREGATE_OK')

    def test_name_of_a_joined_row(self):
        """A row only names an object when it is aggregated by that column."""
        self._run(NAMED_OBJECTS, 'NAMED_OBJECTS_OK')


if __name__ == '__main__':
    unittest.main()
