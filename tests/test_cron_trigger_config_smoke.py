"""
The REST API trigger of a cron group can carry account config for the next
run: the jobs read it from their account, only during that run, every
trigger gets its own run, and the
fields of the account itself can't be set that way.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application import cron_register
from application.helpers.get_account import get_account_by_name
from application.models.account import Account, CustomEntry
from application.models.cron import CronGroup, GroupEntry
from application.modules.plugin import Plugin
from application.plugins.cron import jobs

Account(name='nb', type='netbox', address='https://netbox.example.com',
        custom_fields=[CustomEntry(name='import_filter', value='site:dc1'),
                       CustomEntry(name='delete_host_if_not_found_on_import',
                                   value='True')]).save()
Account(name='other', type='netbox', address='https://other.example.com').save()

seen = []


def job(account):
    """Note what the job sees through the Plugin base of every import
    (CSV, Netbox, ...) and what a lookup of another account sees."""
    data = Plugin(account).config
    seen.append((data.get('import_filter'), data.get('verify_cert'),
                 data['delete_host_if_not_found_on_import'],
                 data['address'], get_account_by_name('other').get('import_filter')))


cron_register['t: job'] = job
group = CronGroup(name='hook', interval='hour', enabled=True, webhook_enabled=True,
                  jobs=[GroupEntry(name='t: job', command='t: job',
                                   account=Account.objects.get(name='nb'))])
token = group.ensure_webhook_token()
group.save()

client = app.test_client()
URL = '/api/v1/syncer/cron/trigger/hook'
HEADERS = {'X-Webhook-Token': token}

answer = client.post(URL, headers=HEADERS,
                     json={'config': {'address': 'https://evil.example.com'}})
eq(answer.status_code, 400, 'account field in config')
if 'address' not in answer.get_json()['error']:
    fail('the answer does not name the refused key')
answer = client.post(URL, headers=HEADERS, json={'config': {'api_token': 'x'}})
eq(answer.status_code, 400, 'secret custom field in config')
answer = client.post(URL, headers=HEADERS, json={'config': ['x']})
eq(answer.status_code, 400, 'config as list')
eq(client.post(URL, headers=HEADERS, json=['x']).status_code, 400, 'body as list')
group.reload()
eq((group.run_once_next, group.run_once_configs), (False, []), 'refused trigger')

answer = client.post(URL, headers=HEADERS, json={'config': {
    'import_filter': 'name:srv01', 'verify_cert': 'false'}})
eq(answer.status_code, 202, 'trigger with config')
app.test_cli_runner().invoke(jobs)
eq(seen, [('name:srv01', False, False, 'https://netbox.example.com', None)],
   'the run with config')
eq(CronGroup.objects.get(name='hook').run_once_configs, [], 'queue after the run')
eq(get_account_by_name('nb')['import_filter'], 'site:dc1', 'account after the run')

# Several triggers before the pass: one run per config, the same config once
for name in ('srv01', 'srv02', 'srv01'):
    eq(client.post(URL, headers=HEADERS, json={'config': {
        'import_filter': f'name:{name}'}}).status_code, 202, f'trigger {name}')
del seen[:]
app.test_cli_runner().invoke(jobs)
eq([entry[0] for entry in seen], ['name:srv01', 'name:srv02'], 'queued runs')

# A trigger without config is a full run, it covers the queued configs
client.post(URL, headers=HEADERS, json={'config': {'import_filter': 'name:srv03'}})
eq(client.post(URL, headers=HEADERS).status_code, 202, 'trigger without body')
del seen[:]
app.test_cli_runner().invoke(jobs)
eq([entry[:3] for entry in seen], [('site:dc1', None, True)],
   'full run instead of the queue')

# The Run button only sets run_once_next: also a full run over the queue
client.post(URL, headers=HEADERS, json={'config': {'import_filter': 'name:srv04'}})
CronGroup.objects(name='hook').update_one(set__run_once_next=True)
del seen[:]
app.test_cli_runner().invoke(jobs)
eq([entry[0] for entry in seen], ['site:dc1'], 'Run button with a queue')
print('CRON_TRIGGER_CONFIG_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CronTriggerConfigTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_trigger_config_reaches_the_job_once(self):
        """Config of the trigger is seen by the job of that run only."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('CRON_TRIGGER_CONFIG_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
