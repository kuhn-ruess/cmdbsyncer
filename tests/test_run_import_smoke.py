"""
Run Import starts the import or the inventorize of the plugin, as the role
of the account says, and the forms refuse what it can not run.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from wtforms.validators import ValidationError

from application.helpers.cron import import_register
from application.helpers.run_import import RUN_IMPORT_JOB, RunImportError, run_import
from application.models.account import Account
from application.models.cron import CronGroup, GroupEntry
from application.helpers.run_import import creates
from application.views.cron import _account_cell, _check_run_import_jobs

calls = []


def recorder(what):
    def function(account, debug=False):
        calls.append((what, account, debug))
    return function


def no_debug(account):
    calls.append(('no_debug', account, None))


# The plugins registered their functions, record instead of running them
eq(sorted(import_register['jdisc']), ['applications', 'devices', 'executables'],
   'jdisc variants')
registered = {account_type: {variant: dict(entry) for variant, entry in variants.items()}
              for account_type, variants in import_register.items()}
for account_type, variants in import_register.items():
    for variant, entry in variants.items():
        for operation in ('import', 'inventorize'):
            if entry[operation]:
                entry[operation] = recorder(f'{account_type}:{variant}:{operation}')
import_register['mysql']['']['import'] = no_debug

Account(name='csv_none', type='csv', enabled=True).save()
Account(name='csv_add', type='csv', restrict_to='inventorize', enabled=True).save()
Account(name='csv_main', type='csv', restrict_to='import', enabled=True).save()
jdisc = Account(name='jdisc', type='jdisc', import_variant='applications',
                enabled=True)
jdisc.save()
Account(name='jdisc_child', is_child=True, parent=jdisc, enabled=True,
        restrict_to='inventorize').save()
Account(name='jdisc_exec', is_child=True, parent=jdisc, enabled=True,
        import_variant='executables').save()
Account(name='vmware', type='vmware_vcenter', enabled=True).save()
Account(name='export', type='csv', restrict_to='export', enabled=True).save()
csv_parent = Account(name='csv_parent', type='csv', restrict_to='inventorize',
                     enabled=True)
csv_parent.save()
Account(name='csv_child', is_child=True, parent=csv_parent, enabled=True).save()
Account(name='mysql', type='mysql', enabled=True).save()
Account(name='bad', type='jdisc', import_variant='nothing', enabled=True).save()

run_import('csv_none', debug=True)
run_import('csv_add')
run_import('csv_main')
run_import('jdisc')
run_import('jdisc_child')
run_import('jdisc_exec')
run_import('mysql', debug=True)
run_import('csv_child')
eq(calls, [
    ('csv::import', 'csv_none', True),
    ('csv::inventorize', 'csv_add', False),
    ('csv::import', 'csv_main', False),
    ('jdisc:applications:import', 'jdisc', False),
    ('jdisc:applications:inventorize', 'jdisc_child', False),
    ('jdisc:executables:import', 'jdisc_exec', False),
    ('no_debug', 'mysql', None),
    ('csv::import', 'csv_child', False),
], 'started functions')

for name, expected in (('vmware', 'set the role of the account to Additional source'),
                       ('bad', "Import from 'nothing' does not exist"),
                       ('export', 'is an export target')):
    try:
        run_import(name)
    except RunImportError as error:
        if expected not in str(error):
            fail(f'{name}: {error}')
    else:
        fail(f'{name}: no error')


def job_check(account):
    group = CronGroup(name='g', jobs=[GroupEntry(name='job', command=RUN_IMPORT_JOB,
                                                 account=account)])
    with app.test_request_context():
        try:
            _check_run_import_jobs(group)
        except ValidationError as error:
            return str(error)
    return None


eq(job_check(Account.objects.get(name='csv_add')), None, 'csv additional job')
if 'Additional source' not in (job_check(Account.objects.get(name='vmware')) or ''):
    fail('vmware job without role was accepted')
if 'export target' not in (job_check(Account.objects.get(name='export')) or ''):
    fail('export target job was accepted')
if 'needs an account' not in (job_check(None) or ''):
    fail('job without account was accepted')

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})
body = check(f'/admin/account/edit/?id={jdisc.id}', 200).get_data(as_text=True)
if 'Import from' not in body or 'Executables' not in body:
    fail('jdisc form without Import from')
body = check(f'/admin/account/edit/?id={Account.objects.get(name="csv_none").id}',
             200).get_data(as_text=True)
if 'Import from' in body:
    fail('csv form with Import from')
if 'Main source: imports hosts and their labels' not in body:
    fail('role choices without explanation')
eq(next(iter(application.cron_register)), RUN_IMPORT_JOB, 'first cron command')
for marker in ('Imports as', 'account-import-fields', 'account-cmdb-object',
               'restrict_to'):
    if marker not in body:
        fail(f'account form without {marker}')
if 'Object Settings' in body:
    fail('account form still has Object Settings')
child_body = check(f'/admin/account_childs/edit/?id={Account.objects.get(name="csv_child").id}',
                   200).get_data(as_text=True)
if 'account-import-fields' not in child_body:
    fail('child form without the import fields block')

location = Account(name='locations', type='csv', is_object=True,
                   object_type='location', enabled=True)
location.save()
eq(creates(location), 'objects: Location', 'object account')
eq(creates(Account.objects.get(name='csv_none')), 'hosts', 'host account')
eq(creates(Account.objects.get(name='csv_add')), 'inventory', 'additional source')
import_register.update(registered)
cell = str(_account_cell(GroupEntry(name='j', command='CSV: Import Hosts',
                                    account=location)))
if 'creates objects: Location' not in cell:
    fail(f'cron cell: {cell}')
cell = str(_account_cell(GroupEntry(name='j', command='Checkmk: Export Hosts',
                                    account=location)))
if 'creates' in cell:
    fail(f'export job cell: {cell}')
from application.helpers.plugins import plugin_jobs
from application.models.account import PluginSettings
from application.views.account import _check_variant
csv_jobs = plugin_jobs('csv')
if 'CSV: Import Hosts' not in csv_jobs or 'Checkmk: Export Hosts' in csv_jobs \
        or RUN_IMPORT_JOB in csv_jobs:
    fail(f'jobs offered for csv: {csv_jobs}')
if 'Checkmk: Export Hosts' not in plugin_jobs('cmkv2'):
    fail('checkmk jobs missing for cmkv2')
wrong = Account(name='wrong', type='csv',
                plugin_settings=[PluginSettings(plugin='Checkmk: Export Hosts')])
try:
    _check_variant(wrong, 'csv')
except ValidationError as error:
    if 'is no job of accounts of type csv' not in str(error):
        fail(str(error))
else:
    fail('plugin settings of another plugin accepted')
if 'pluginJobs' not in body:
    fail('account form without the plugin job filter')
print('RUN_IMPORT_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class RunImportTests(unittest.TestCase):
    """Runs the snippet against the booted app."""

    def test_run_import_follows_the_role(self):
        """Import, inventorize and variant as the account says."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('RUN_IMPORT_OK', result.stdout)
