"""
Account secrets reach a host's cache through rule outcomes and the debug page
through the {{ACCOUNT:...}} macro. Neither hands them to a user who may not
manage accounts.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application import limiter
from application.helpers.get_account import SECRET_PLACEHOLDER, mask_account_secrets
from application.helpers.syncer_jinja import render_jinja
from application.models.account import Account, CustomEntry
from application.models.host import Host

limiter.enabled = False

SECRET = 'very-secret-value'


def login(email, roles):
    global client
    new = User(email=email, name=email, roles=roles)
    new.set_password('smoke-password')
    new.save()
    client = app.test_client()
    client.post('/login', data={
        'login_email': email, 'password': 'smoke-password',
        'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
    })


# --- the macro: real value in a run, placeholder on the debug page
account = Account(name='acc', type='csv', address='https://acc.example.com', username='user',
                  custom_fields=[CustomEntry(name='api_token', value=SECRET),
                                 CustomEntry(name='bakery_passphrase', value=SECRET),
                                 CustomEntry(name='site', value='plain-value')])
account.save()
for field in ('api_token', 'bakery_passphrase'):
    eq(render_jinja('{{ACCOUNT:acc:' + field + '}}'), SECRET, f'{field} in a run')
    with mask_account_secrets() as masking:
        eq(render_jinja('{{ACCOUNT:acc:' + field + '}}'), SECRET_PLACEHOLDER, f'{field} masked')
    eq(masking.used, True, f'masking of {field} is reported')
with mask_account_secrets():
    eq(render_jinja('{{ACCOUNT:acc:site}}'), 'plain-value', 'a plain field stays readable')
    eq(render_jinja('{{ACCOUNT:acc:address}}'), 'https://acc.example.com', 'the address too')

# --- the cache: values only with the account role
host = Host(hostname='cached', source_account_id='acc', source_account_name='acc',
            cache={'checkmk_rules': {'outcome': SECRET}})
host.save()
url = f'/admin/host/details/?id={host.id}'

login('hosts@example.com', ['host'])
body = check(url, 200).get_data(as_text=True)
eq('1 cache entrie(s)' in body, True, 'the count stays')
eq(SECRET in body, False, 'the value without the account role')
eq('View Cache Details' in body, False, 'the button without the account role')

login('accounts@example.com', ['host', 'account'])
body = check(url, 200).get_data(as_text=True)
eq(SECRET in body, True, 'the value with the account role')

# --- the other pages rendering rules: the plugin role alone sees no secret
# pylint: disable=wrong-import-position
from application.plugins.checkmk.models import (
    CheckmkRule, CheckmkRuleMngmt, CheckmkRuleOutcome, RuleMngmtOutcome)
from application.plugins.checkmk.user_models import (
    CheckmkUserGenerationRule, CmkUserGenerationOutcome)

MACRO = '{{ACCOUNT:acc:api_token}}'

list_rule = CheckmkRuleMngmt(
    name='secret-list-rule', enabled=True, condition_typ='anyway', rule_source='list',
    list_source='Service;Level\\nsrv01;10\\n',
    outcomes=[RuleMngmtOutcome(ruleset='r', folder='/', value_template="'" + MACRO + "'",
                               condition_service='{{ service }}$')])
list_rule.save()

generation = CheckmkUserGenerationRule(name='secret-generation', enabled=True)
generation.outcome = CmkUserGenerationOutcome(
    foreach_type='label', foreach='ldap_group', rewrite_group_name='{{name}}',
    rewrite_user_id='{{name}}', rewrite_full_name=MACRO, roles=['user'])
generation.save()

folder_host = Host.get_host('secret-folder-host')
folder_host.update_host({'ldap_group': 'grp-dba'})
folder_host.save()
CheckmkRule(name='secret-folder-rule', enabled=True, condition_typ='anyway',
            outcomes=[CheckmkRuleOutcome(
                action='move_folder',
                action_param="shared|{'contactgroups': {'groups': ['" + MACRO
                             + "'], 'use': True}}")]).save()
# What a real run cached holds the real value, the preview must not read it
cached_host = Host(hostname='secret-cached-host', source_account_name='acc',
                   source_account_id='acc', labels={'ldap_group': 'grp-dba'},
                   cache={'cmk_conf_hostattribute': {'attributes': {
                       'all': {'ldap_group': SECRET}, 'filtered': {}}}})
cached_host.save()
caches_before = {x.hostname: x.cache for x in Host.objects()}

login('checkmk@example.com', ['checkmk'])
for page in (f'/admin/checkmkrulemngmt/list_rule_debug?id={list_rule.id}',
             '/admin/checkmk_user_generation_preview/?preview=1',
             '/admin/checkmk_folders/?calculate=1',
             '/admin/checkmk_folders/debug?folder=/shared'):
    body = check(page, 200).get_data(as_text=True)
    eq(SECRET in body, False, f'the secret on {page}')
eq(SECRET_PLACEHOLDER in check('/admin/checkmk_folders/debug?folder=/shared', 200)
   .get_data(as_text=True), True, 'the placeholder on the folder debug')
eq({x.hostname: x.cache for x in Host.objects()}, caches_before,
   'the host caches after these pages')
# A run still gets the real value
eq(render_jinja(MACRO), SECRET, 'the macro after these pages')

print('SECRET_EXPOSURE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class AccountSecretExposureTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_exposure(self):
        """Debug page and cache keep the secret from those without the role."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('SECRET_EXPOSURE_OK', result.stdout)
