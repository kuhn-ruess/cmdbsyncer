"""
The call before the update of a Checkmk site: what the inventory of the
sites hands the playbook, rendered per server and site.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import json
from application.models.account import Account
from application.plugins.ansible.site_syncer import SyncSites
from application.plugins.checkmk.models import AnsibleVariable, CheckmkSettings, CheckmkSite

account = Account(name='snapshot', type='csv', address='', enabled=True)
account.set_password('tok123')
account.save()

body = ('{"Parameters": {"Beschreibung": "Update to {{ CMK_VERSION }}", '
        '"Snapshot Name": "cmk-{{ SITE }}-{{ CMK_VERSION }}", "VM Name": "{{ SERVER }}", '
        '"vCenter Host": "{{ vcenter_host }}"}}')
settings = CheckmkSettings(name='prod', cmk_version='2.4.0p15', cmk_edition='cee',
                           pre_update_url='https://automation.example.com/hook',
                           pre_update_token='{{ACCOUNT:snapshot:password}}',
                           pre_update_body=body,
                           pre_update_success_field='item2.workflowStatus',
                           pre_update_success_value='Completed')
settings.save()
site = CheckmkSite(name='mysite', server_address='srv01.example.com', settings_master=settings,
                   enabled=True, custom_ansible_variables=[
                       AnsibleVariable(variable_name='vcenter_host', variable_value='vc01.example.com')])
site.save()

data = SyncSites(settings).get_site_data(site)
eq(data['cmk_pre_update_url'], 'https://automation.example.com/hook', 'url')
eq(data['cmk_pre_update_token'], 'tok123', 'token from the account')
eq(json.loads(data['cmk_pre_update_body']), {'Parameters': {
    'Beschreibung': 'Update to 2.4.0p15', 'Snapshot Name': 'cmk-mysite-2.4.0p15',
    'VM Name': 'srv01.example.com', 'vCenter Host': 'vc01.example.com'}}, 'rendered body')
eq((data['cmk_pre_update_success_field'], data['cmk_pre_update_success_value'],
    data['cmk_pre_update_timeout']), ('item2.workflowStatus', 'Completed', 600), 'success check')
eq(data['vcenter_host'], 'vc01.example.com', 'custom variable still in the inventory')

# --- without a URL there is no call
settings.pre_update_url = ''
settings.save()
site.reload()
eq([key for key in SyncSites(settings).get_site_data(site) if key.startswith('cmk_pre_update')],
   [], 'call variables without a URL')

# --- the form has the section
client.post('/login', data={'login_email': 'smoke@example.com', 'password': 'smoke-password',
                            'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login')})
page = check('/admin/checkmksettings/new/', 200).get_data(as_text=True)
eq('Before the Update: Call a URL' in page and 'name="pre_update_body"' in page, True,
   'form section')
print('PRE_UPDATE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class PreUpdateCallTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_inventory_carries_the_call(self):
        """URL, token from an account, body per server and site"""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('PRE_UPDATE_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
