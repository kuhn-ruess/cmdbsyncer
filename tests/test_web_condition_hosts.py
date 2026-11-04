"""
Option "Create missing Hosts" of a Checkmk Setup Rule: the export creates the
hosts its Condition — Host name names, nothing else may create them.

Runs against the real app like ``tests/test_web_requests_smoke.py``, see
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


CONDITION_HOSTS = LOGIN + '''
from unittest.mock import patch

from application.models.host import Host
from application.plugins.checkmk.cmk2 import CMK2
from application.plugins.checkmk.cmk_rules import CheckmkRuleSync
from application.plugins.checkmk.models import CheckmkRuleMngmt


def make_sync(dry_run=False, scope=None):
    """A sync that talks to no Checkmk."""
    with patch.object(CMK2, '__init__', lambda self, *_a, **_k: None):
        sync = CheckmkRuleSync()
    sync.account_name = 'cmk'
    sync.account_id = 'cmk-id'
    sync.project = None
    sync.checkmk_version = '2.3.0'
    sync.config = {'limit_by_folders': scope}
    sync.log_details = []
    sync.dry_run = dry_run
    sync.dry_run_plan = []
    sync.drop_unsupported_conditions = lambda *_a: None
    return sync


def build(sync, condition, folder='/', create=True, templates=('tpl',)):
    """Render one outcome the way the export does."""
    return sync.build_condition_and_update_rule_params({
        'ruleset': 'checkgroup_parameters:filesystem', 'folder': folder,
        'value_template': '{}', 'condition_host': condition,
        'create_condition_hosts': create, 'create_host_templates': list(templates),
    }, {'all': {'HOSTNAME': None}})


def hostnames():
    return sorted(host.hostname for host in Host.objects())


Host(hostname='known', source_account_name='other', source_account_id='1').save()
Host(hostname='tpl', object_type='template').save()
CONDITION = 'new-a,known,new_b.example.com,~regex.*,{{ HOSTNAME }}'

# The form offers the option
body = check('/admin/checkmkrulemngmt/new/', 200).get_data(as_text=True)
for field in ('create_condition_hosts', 'create_host_templates'):
    if field not in body:
        fail(f'the form does not offer {field}')

# Rendering alone, as previews do it, creates nothing and sends no flag along
sync = make_sync()
rule = build(sync, CONDITION)
for key in ('create_condition_hosts', 'create_host_templates', 'condition_host'):
    eq(key in rule, False, f'{key} in the rule payload')
eq(rule['condition']['host_name']['match_on'],
   ['new-a', 'known', 'new_b.example.com', '~regex.*', 'None'], 'condition')
eq(hostnames(), ['known', 'tpl'], 'hosts after rendering')

# Without the option, or outside the folder scope, no name is collected
sync = make_sync(scope='/allowed')
build(sync, CONDITION, create=False)
build(sync, CONDITION, folder='/elsewhere')
eq(sync._condition_hosts, {}, 'hosts collected without the option')

# A dry run plans the missing hosts only
sync = make_sync(dry_run=True)
build(sync, CONDITION)
sync._create_condition_hosts()
eq(sorted(entry[1] for entry in sync.dry_run_plan),
   ['new-a', 'new_b.example.com'], 'dry run plan')
eq(hostnames(), ['known', 'tpl'], 'hosts after the dry run')

# The real run creates exactly the missing ones
sync = make_sync()
build(sync, CONDITION)
sync._create_condition_hosts()
eq(hostnames(), ['known', 'new-a', 'new_b.example.com', 'tpl'], 'hosts after the export')
new = Host.objects.get(hostname='new-a')
eq((new.source_account_name, new.is_object), ('cmdb', False), 'created host')
eq([t.hostname for t in new.cmdb_templates], ['tpl'], 'templates of the created host')
known = Host.objects.get(hostname='known')
eq((known.source_account_name, list(known.cmdb_templates)), ('other', []), 'existing host')
details = dict(sync.log_details)
eq(details['condition_hosts_created'], 'new-a, new_b.example.com', 'log detail')
eq(sorted(v for k, v in sync.log_details if k == 'condition_host_not_created'),
   ['None', '~regex.*'], 'names left out')

# The next run has nothing left to do
sync = make_sync()
build(sync, CONDITION)
sync._create_condition_hosts()
eq('condition_hosts_created' in dict(sync.log_details), False, 'second run')

# A template that is gone reports that host and does not stop the export
sync = make_sync()
build(sync, 'gone-template', templates=['gone'])
build(sync, 'no-template', templates=[])
sync._create_condition_hosts()
if not any('gone-template' in str(value) for _key, value in sync.log_details):
    fail('a host that could not be created is not reported')
eq('gone-template' in hostnames(), False, 'host with a template that is gone')
eq('no-template' in hostnames(), True, 'host without a template')

# The form stores the option and the templates
url = '/admin/checkmkrulemngmt/new/'
check(url, 302, method='post', data={
    'csrf_token': csrf(url), 'name': 'form-rule', 'condition_typ': 'anyway',
    'static_rule': 'y', 'rule_source': 'hosts',
    'outcomes-0-ruleset': 'checkgroup_parameters:filesystem',
    'outcomes-0-folder': '/', 'outcomes-0-value_template': '{}',
    'outcomes-0-condition_host': 'form-host',
    'outcomes-0-create_condition_hosts': 'y',
    'outcomes-0-create_host_templates': 'tpl',
})
saved = CheckmkRuleMngmt.objects.get(name='form-rule')
eq(saved.outcomes[0].create_condition_hosts, True, 'stored option')
eq(list(saved.outcomes[0].create_host_templates), ['tpl'], 'stored templates')
sync = make_sync()
sync.rulsets_by_type = {}
sync.static_rules = [saved]
sync.calculate_static_rules()
sync._create_condition_hosts()
eq([t.hostname for t in Host.objects.get(hostname='form-host').cmdb_templates],
   ['tpl'], 'templates of a host from a saved rule')
print('CONDITION_HOSTS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestWebConditionHosts(unittest.TestCase):
    """Creating the hosts named by a rule condition, in both CMDB modes."""

    def test_condition_hosts(self):
        """Only the export creates them, and only hosts that are missing."""
        for cmdb_mode in ('False', 'True'):
            with self.subTest(cmdb_mode=cmdb_mode):
                result = run_against_app(CONDITION_HOSTS, cmdb_mode)
                self.assertEqual(result.returncode, 0,
                                 f"{result.stdout}\n{result.stderr}")
                self.assertIn('CONDITION_HOSTS_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
