"""
Run Jobs defined by Account runs the jobs the account lists, or the import
or inventorize its role says, and the forms refuse what it can not run.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from wtforms.validators import ValidationError

from application import app, cron_register
from application.helpers.cron import import_register
from application.helpers.account_jobs import (ACCOUNT_JOBS_JOB, AccountJobsError,
                                              creates, run_account_jobs)
from application.helpers.plugins import plugin_jobs
from application.models.account import Account, PluginSettings
from application.models.cron import CronGroup, GroupEntry
from application.views.account import (_check_jobs, _store_inventory_key, child_name,
                                       without_cron)
from application.views.cron import _account_cell, _check_account_jobs

calls = []
originals = dict(cron_register)
registered = {account_type: [dict(entry) for entry in entries]
              for account_type, entries in import_register.items()}
replaced = {}


def recorder(job):
    def function(account, debug=False):
        calls.append((job, account, debug))
    return function


# Record instead of running: the same new function in the cron register
# and the import register, so the kind of each job is still known
for job, function in list(cron_register.items()):
    if job == ACCOUNT_JOBS_JOB:
        continue
    new = recorder(job)
    replaced[function] = new
    cron_register[job] = new
for entries in import_register.values():
    for entry in entries:
        for operation in ('import', 'inventorize'):
            if entry[operation] in replaced:
                entry[operation] = replaced[entry[operation]]


def no_debug(account):
    calls.append(('no_debug', account, None))


import_register['mysql'][0]['import'] = no_debug

Account(name='csv_none', type='csv', enabled=True).save()
Account(name='csv_add', type='csv', restrict_to='inventorize', enabled=True).save()
jdisc = Account(name='jdisc', type='jdisc', enabled=True,
                account_jobs=['JDisc: Import Applications', 'JDisc: Import Devices'])
jdisc.save()
Account(name='jdisc_child', is_child=True, parent=jdisc, enabled=True).save()
Account(name='jdisc_own', is_child=True, parent=jdisc, enabled=True,
        restrict_to='inventorize',
        account_jobs=['JDisc: Inventorize Executables']).save()
Account(name='mysql', type='mysql', enabled=True).save()
Account(name='vmware', type='vmware_vcenter', enabled=True).save()
Account(name='export', type='cmkv2', restrict_to='export', enabled=True,
        account_jobs=['Checkmk: Export Hosts', 'Checkmk: Activate Changes']).save()
Account(name='export_empty', type='cmkv2', restrict_to='export', enabled=True).save()
Account(name='main_inv', type='csv', restrict_to='import', enabled=True,
        account_jobs=['CSV: Inventorize Hosts']).save()
Account(name='foreign', type='csv', enabled=True,
        account_jobs=['Checkmk: Export Hosts']).save()

for name, debug in (('csv_none', True), ('csv_add', False), ('jdisc', False),
                    ('jdisc_child', False), ('jdisc_own', False), ('mysql', True),
                    ('export', False)):
    run_account_jobs(name, debug)
eq(calls, [
    ('CSV: Import Hosts', 'csv_none', True),
    ('CSV: Inventorize Hosts', 'csv_add', False),
    ('JDisc: Import Applications', 'jdisc', False),
    ('JDisc: Import Devices', 'jdisc', False),
    ('JDisc: Import Applications', 'jdisc_child', False),
    ('JDisc: Import Devices', 'jdisc_child', False),
    ('JDisc: Inventorize Executables', 'jdisc_own', False),
    ('no_debug', 'mysql', None),
    ('Checkmk: Export Hosts', 'export', False),
    ('Checkmk: Activate Changes', 'export', False),
], 'started jobs')

for name, expected in (('vmware', 'vmware_vcenter can not import'),
                       ('export_empty', 'is an export target'),
                       ('main_inv', 'does not allow CSV: Inventorize Hosts'),
                       ('foreign', 'is no job of accounts of type csv')):
    try:
        run_account_jobs(name)
    except AccountJobsError as error:
        if expected not in str(error):
            fail(f'{name}: {error}')
    else:
        fail(f'{name}: no error')


def job_check(account):
    group = CronGroup(name='g', jobs=[GroupEntry(name='job', command=ACCOUNT_JOBS_JOB,
                                                 account=account)])
    try:
        _check_account_jobs(group)
    except ValidationError as error:
        return str(error)
    return None


eq(job_check(Account.objects.get(name='export')), None, 'export target with jobs')
if 'export target' not in (job_check(Account.objects.get(name='export_empty')) or ''):
    fail('export target without jobs was accepted')
if 'needs an account' not in (job_check(None) or ''):
    fail('job without account was accepted')

for name in ('main_inv', 'foreign'):
    account = Account.objects.get(name=name)
    try:
        _check_jobs(account, account.type)
    except ValidationError:
        pass
    else:
        fail(f'account form accepted the jobs of {name}')
wrong = Account(name='wrong', type='csv',
                plugin_settings=[PluginSettings(plugin='Checkmk: Export Hosts')])
try:
    _check_jobs(wrong, 'csv')
except ValidationError as error:
    if 'is no job of accounts of type csv' not in str(error):
        fail(str(error))
else:
    fail('plugin settings of another plugin accepted')

own = Account.objects.get(name='jdisc_own')
eq(child_name(Account(parent=jdisc, is_child=True,
                      account_jobs=['JDisc: Inventorize Executables'])),
   'jdisc-inventorize-executables', 'child name from the first job')
eq(child_name(Account(parent=jdisc, is_child=True, restrict_to='export')),
   'jdisc-export', 'child name from the role')
Account(name='jdisc-child', is_child=True, parent=jdisc).save()
eq(child_name(Account(parent=jdisc, is_child=True)), 'jdisc-child-2', 'taken child name')


class KeyForm:  # pylint: disable=too-few-public-methods
    class inventory_key:  # pylint: disable=invalid-name,too-few-public-methods
        data = ' snow '


_store_inventory_key(KeyForm, own)
_store_inventory_key(KeyForm, own)
eq([(x.name, x.value) for x in own.custom_fields], [('inventorize_key', 'snow')],
   'inventory key stored once')

netbox = Account(name='netbox', type='netbox', restrict_to='import', object_type='host',
                 account_jobs=['Netbox: Import Devices', 'Netbox: Import VMs'])
_check_jobs(netbox, 'netbox')
eq(netbox.object_type, 'auto', 'object type with several import jobs')
netbox.account_jobs = ['Netbox: Import Devices', 'Netbox: Update IPs']
netbox.object_type = 'host'
_check_jobs(netbox, 'netbox')
eq(netbox.object_type, 'host', 'object type with one import job')

csv_jobs = plugin_jobs('csv')
if 'CSV: Import Hosts' not in csv_jobs or 'Checkmk: Export Hosts' in csv_jobs \\
        or ACCOUNT_JOBS_JOB in csv_jobs:
    fail(f'jobs offered for csv: {csv_jobs}')
eq(next(iter(application.cron_register)), ACCOUNT_JOBS_JOB, 'first cron command')

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})
body = check(f'/admin/account/edit/?id={jdisc.id}', 200).get_data(as_text=True)
for marker in ('Main source: imports hosts and their labels', 'Imports as',
               'account-object-type',
               'account-import-fields', 'account-cmdb-object', 'account_jobs-0',
               'pluginJobs'):
    if marker not in body:
        fail(f'account form without {marker}')
if 'Object Settings' in body or 'Import from' in body:
    fail('account form with removed fields')
child_body = check(
    f'/admin/account_childs/edit/?id={Account.objects.get(name="jdisc_own").id}',
    200).get_data(as_text=True)
if 'account-import-fields' not in child_body or 'account_jobs-0' not in child_body \\
        or 'account-inventory-key' not in child_body:
    fail('child form without import fields or jobs')
CronGroup(name='runs_export', jobs=[GroupEntry(
    name='job', command=ACCOUNT_JOBS_JOB,
    account=Account.objects.get(name='export'))]).save()
with app.test_request_context():
    eq(without_cron(Account.objects.get(name='export')), False, 'account in a cron job')
    eq(without_cron(Account.objects.get(name='csv_add')), True, 'role, no cron job')
    eq(without_cron(Account.objects.get(name='csv_none')), False, 'no role')
Account(name='filtered', type='csv', plugin_settings=[
    PluginSettings(plugin='Checkmk: Export Hosts', object_filter=['host', 'service'])]).save()
listing = check('/admin/account/', 200).get_data(as_text=True)
if 'host, service' not in listing:
    fail('account list without the object filter of the plugin settings')
if 'In no cron job' not in listing or '"no_cron": true' not in listing:
    fail('account list without the hint for accounts in no cron job')
for marker in ('"jdisc_own"', 'Add child account', f'data-id="{jdisc.id}"'):
    if marker not in listing:
        fail(f'account list without {marker}')
if 'Account Overrides' in listing:
    fail('menu still lists the child accounts on their own')
created = check(f'/admin/account_childs/new/?parent={jdisc.id}', 200).get_data(as_text=True)
if f'value="{jdisc.id}" selected' not in created \
        and f'selected value="{jdisc.id}"' not in created:
    fail('child create form without the parent')

cron_register.update(originals)
import_register.update(registered)
location = Account(name='locations', type='csv', is_object=True,
                   object_type='location', enabled=True)
location.save()
eq(creates(location), 'objects: Location', 'object account')
eq(creates(Account.objects.get(name='csv_none')), 'hosts', 'host account')
eq(creates(Account.objects.get(name='csv_add')), 'inventory', 'additional source')
eq(creates(Account.objects.get(name='export')), None, 'export target')
cell = str(_account_cell(GroupEntry(name='j', command='CSV: Import Hosts',
                                    account=location)))
if 'creates objects: Location' not in cell:
    fail(f'cron cell: {cell}')
cell = str(_account_cell(GroupEntry(name='j', command='Checkmk: Export Hosts',
                                    account=location)))
if 'creates' in cell:
    fail(f'export job cell: {cell}')
print('ACCOUNT_JOBS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class AccountJobsTests(unittest.TestCase):
    """Runs the snippet against the booted app."""

    def test_account_runs_its_jobs(self):
        """The jobs of the account, or what its role says."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('ACCOUNT_JOBS_OK', result.stdout)
