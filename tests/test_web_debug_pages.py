"""
The debug pages of a Setup Rule rendered from a list and of a CMDB object
must render and show what they promise: the rows and the Checkmk rules the
export would send, and the attributes and rule groups of an object.

Runs against the real app like ``tests/test_web_requests_smoke.py``, see
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


LIST_RULE_DEBUG = LOGIN + '''
from application.plugins.checkmk.models import CheckmkRuleMngmt, RuleMngmtOutcome

rule = CheckmkRuleMngmt(
    name='smoke-list-rule', enabled=True, condition_typ='anyway',
    rule_source='list',
    list_source='Service;Level\\nDisk C:;10\\nMemory;20\\nCPU load;10\\nSwap;\\n',
    outcomes=[RuleMngmtOutcome(
        ruleset='extra_service_conf:_ec_sl', folder='/',
        value_template='{{ level }}', condition_service='{{ service }}$')])
rule.save()
if not rule.static_rule:
    fail('a list rule was not saved as host-independent')

page = f'/admin/checkmkrulemngmt/list_rule_debug?id={rule.id}'
body = check(page, 200).get_data(as_text=True)
# Rows with the same level are joined into one rule, in row order
# (quotes are HTML escaped on the page)
for needle in ('extra_service_conf:_ec_sl', 'Disk C:$&#39;, &#39;CPU load$',
               'Memory$', '2 after joining', '{{ service }}', '{{ level }}'):
    if needle not in body:
        fail(f'the list rule debug page does not show {needle!r}')
# The row without a level produced no rule
if 'lrd-skip' not in body:
    fail('the row without a Value is not marked as producing no rule')

# A rule rendered per host points to the host debug page instead
host_rule = CheckmkRuleMngmt(
    name='smoke-host-rule', enabled=True, condition_typ='anyway',
    outcomes=[RuleMngmtOutcome(ruleset='extra_host_conf:_ec_sl', folder='/',
                               value_template='10')])
host_rule.save()
body = check(f'/admin/checkmkrulemngmt/list_rule_debug?id={host_rule.id}',
             200).get_data(as_text=True)
if f'preview_rule_id=setup_rule:{host_rule.id}' not in body:
    fail('a per host rule does not link the host debug page')

# The rule list and the edit form link the debug page
listing = check('/admin/checkmkrulemngmt/', 200).get_data(as_text=True)
if 'list_rule_debug' not in listing:
    fail('the Setup Rule list does not link the rule debug page')
form = check(f'/admin/checkmkrulemngmt/edit/?id={rule.id}', 200).get_data(as_text=True)
if f'list_rule_debug?id={rule.id}' not in form:
    fail('the Setup Rule form does not link the rule debug page')
print('LIST_RULE_DEBUG_OK')
'''


OBJECT_DEBUG = LOGIN + '''
from application.models.host import Host

obj = Host.get_host('smoke-object')
obj.is_object = True
obj.object_type = 'application'
obj.update_host({'owner_team': 'team-ops'})
obj.save()

page = f'/admin/Objects/debug?obj_id={obj.id}'
body = check(page, 200).get_data(as_text=True)
for needle in ('smoke-object', 'application', 'Edit object', 'team-ops',
               'Full Attribute List'):
    if needle not in body:
        fail(f'the object debug page does not show {needle!r}')

# The object specific Netbox rule types are evaluated as rule groups
body = check(page + '&mode=netbox_object', 200).get_data(as_text=True)
for needle in ('IP Addresses', 'Prefixes', 'Contacts', 'Dataflow'):
    if needle not in body:
        fail(f'the Netbox object debug does not show the {needle!r} rules')

# By name, like the host debug page
check('/admin/Objects/debug?hostname=smoke-object', 200)

listing = check('/admin/Objects/', 200).get_data(as_text=True)
if 'Objects/debug?obj_id=' not in listing:
    fail('the object list does not link the debug page')
print('OBJECT_DEBUG_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestWebDebugPages(unittest.TestCase):
    """The rule and object debug pages, in both CMDB modes."""

    def _run(self, snippet, marker):
        """Run `snippet` for both CMDB_MODE values; assert both succeed."""
        for cmdb_mode in ('False', 'True'):
            with self.subTest(cmdb_mode=cmdb_mode):
                result = run_against_app(snippet, cmdb_mode)
                self.assertEqual(
                    result.returncode, 0,
                    f"CMDB_MODE={cmdb_mode}:\n{result.stdout}\n{result.stderr}")
                self.assertIn(marker, result.stdout)

    def test_list_rule_debug_page(self):
        """Rows and the joined Checkmk rules of a list rule."""
        self._run(LIST_RULE_DEBUG, 'LIST_RULE_DEBUG_OK')

    def test_object_debug_page(self):
        """An object is debuggable like a host, Netbox object rules included."""
        self._run(OBJECT_DEBUG, 'OBJECT_DEBUG_OK')


if __name__ == '__main__':
    unittest.main()
