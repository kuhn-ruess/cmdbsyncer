"""
Every rule type with a list source gets the same form part from
``ListSourceViewMixin``: the Rule source switch, the List field with its
live preview and the preview endpoint. Checked for every rule type with a
list against the real app.

Runs against the real app like ``tests/test_web_requests_smoke.py``, see
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


LIST_SOURCE_FORMS = LOGIN + '''
from application.plugins.checkmk.models import (
    CheckmkDCDRule, DCDRuleOutcome, CheckmkRuleMngmt, RuleMngmtOutcome)

for base, field in (('/admin/checkmkrulemngmt', 'value_template'),
                    ('/admin/checkmkdcdrule', 'dcd_id')):
    form = check(f'{base}/new/', 200).get_data(as_text=True)
    for needle in ('id="rule_source"', 'id="list_source"',
                   'list-source-preview', 'Pasted List'):
        if needle not in form:
            fail(f'the form at {base} does not show {needle!r}')
    token = csrf(f'{base}/new/')
    answer = check(f'{base}/_list_source_preview', 200, method='post',
                   headers={'X-CSRFToken': token},
                   data={'list_source': 'ID;Site\\nsrv01;site_a\\nsrv02;site_b\\n',
                         f'outcomes-0-{field}': '{{ idd }}'}).get_json()
    eq(answer['columns'], ['id', 'site'], f'columns of {base}')
    eq(answer['row_count'], 2, f'row count of {base}')
    eq(answer['delimiter'], 'semicolon', f'separator of {base}')
    if not any("'{{ idd }}' is not a column" in text for text in answer['warnings']):
        fail(f'{base} does not warn about a variable that is no column')

# A DCD rule rendered from its list is saved as host-independent, its form
# shows the list but links no debug page (only Setup Rules have one).
dcd = CheckmkDCDRule(
    name='smoke-dcd-list', enabled=True, condition_typ='anyway',
    rule_source='list', list_source='id\\ndc1\\n',
    outcomes=[DCDRuleOutcome(dcd_id='{{ id }}', title='{{ id }}', site='s')])
dcd.save()
if not dcd.static_rule:
    fail('a DCD list rule was not saved as host-independent')
form = check(f'/admin/checkmkdcdrule/edit/?id={dcd.id}', 200).get_data(as_text=True)
if 'list-source-preview' not in form or 'list_rule_debug' in form:
    fail('the DCD rule form does not show the list part as expected')
listing = check('/admin/checkmkdcdrule/', 200).get_data(as_text=True)
if 'dc1' in listing:
    fail('the DCD rule list shows the pasted list as a column')

# A rule saved before the switch existed opens in the mode it is exported in
legacy = CheckmkRuleMngmt(
    name='smoke-legacy-list', enabled=True, condition_typ='anyway',
    list_source='service\\nDisk C:\\n',
    outcomes=[RuleMngmtOutcome(ruleset='r', folder='/', value_template='1')])
legacy.save()
form = check(f'/admin/checkmkrulemngmt/edit/?id={legacy.id}', 200).get_data(as_text=True)
if '<option selected value="list">' not in form and \\
        'value="list" selected' not in form:
    fail('a rule with a list but without rule source does not open as list rule')

# Every other rule type with a list shows it in its form, with its own
# outcome fields checked by the preview.
for base, field in (('/admin/idoitcustomattributes', 'param'),
                    ('/admin/jiraexportrule', 'value'),
                    ('/admin/checkmkbirule', 'rule_template'),
                    ('/admin/checkmkbiaggregation', 'rule_template'),
                    ('/admin/checkmkdowntimerule', 'downtime_comment'),
                    ('/admin/checkmknotificationrule', 'match_hosts'),
                    ('/admin/netboxcustomattributes', 'param'),
                    ('/admin/netboxcontactattributes', 'param'),
                    ('/admin/netboxdataflowattributes', 'field_value'),
                    ('/admin/netboxdciminterfaceattributes', 'param'),
                    ('/admin/netboxvirtualizationinterfaceattributes', 'param'),
                    ('/admin/netboxipamipaddressattributes', 'param'),
                    ('/admin/vmwarecustomattributes', 'attribute_value'),
                    ('/admin/ansiblecustomvariablesrule', 'attribute_value')):
    form = check(f'{base}/new/', 200).get_data(as_text=True)
    for needle in ('id="rule_source"', 'id="list_source"', 'list-source-preview'):
        if needle not in form:
            fail(f'the form at {base} does not show {needle!r}')
    token = csrf(f'{base}/new/')
    answer = check(f'{base}/_list_source_preview', 200, method='post',
                   headers={'X-CSRFToken': token},
                   data={'list_source': 'hostname,room\\nsrv01,r1\\n',
                         f'outcomes-0-{field}': '{{ rooom }}'}).get_json()
    eq(answer['columns'], ['hostname', 'room'], f'columns of {base}')
    if not any("'{{ rooom }}' is not a column" in text for text in answer['warnings']):
        fail(f'{base} does not warn about a variable that is no column')
# The notification rule form keeps its own page parts next to the list.
form = check('/admin/checkmknotificationrule/new/', 200).get_data(as_text=True)
if '_notification_plugins' not in form:
    fail('the notification rule form lost its own page parts')
print('LIST_SOURCE_FORMS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestWebListSource(unittest.TestCase):
    """The list source form part of every rule type with a list."""

    def test_list_source_forms(self):
        """Switch, preview endpoint and saving, in both CMDB modes."""
        for cmdb_mode in ('False', 'True'):
            with self.subTest(cmdb_mode=cmdb_mode):
                result = run_against_app(LIST_SOURCE_FORMS, cmdb_mode)
                self.assertEqual(
                    result.returncode, 0,
                    f"CMDB_MODE={cmdb_mode}:\n{result.stdout}\n{result.stderr}")
                self.assertIn('LIST_SOURCE_FORMS_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
