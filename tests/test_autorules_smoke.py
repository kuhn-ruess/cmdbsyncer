"""
Autocreate rules: an attribute value is a value. It can't add fields to the
rule it ends up in, and a host the rules ignore doesn't stop the run.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application.models.host import Host
from application.plugins.rules.autorules import RuleCreation
from application.plugins.rules.models import SyncerRuleAutomation
from application.plugins.checkmk.models import CheckmkFolderPool

BODY = """{
  "name": "Pool {{ site_id }}",
  "folder_name": "/{{ site_id }}",
  "folder_title": "{{ alias }}",
  "folder_seats": 10,
  "enabled": false
}"""

SyncerRuleAutomation(name='pools', rule_type='cmk_folder_pool', object_filter='application',
                     rule_body=BODY, enabled=True).save()


def add_host(hostname, labels):
    host = Host(hostname=hostname, object_type='application', source_account_name='x')
    host.labels = labels
    host.save()
    return host


def run(ignored=()):
    creation = RuleCreation()
    real = creation.get_attributes

    def attributes(host, cache):
        return False if host.hostname in ignored else real(host, cache)

    creation.get_attributes = attributes
    creation.create_rules()


# --- plain values work as before
add_host('srv01', {'site_id': 'site1', 'alias': 'Site 1'})
run()
eq(CheckmkFolderPool.objects.get(name='Pool site1').folder_title, 'Site 1', 'plain value')

# --- a value can't close the string and add a field
add_host('srv02', {'site_id': 'site2',
                   'alias': 'x", "enabled": true, "folder_seats": 999, "a": "'})
run()
pool = CheckmkFolderPool.objects.get(name='Pool site2')
eq(pool.enabled, False, 'field set from an attribute value')
eq(pool.folder_seats, 10, 'number set from an attribute value')
eq(pool.folder_title, 'x", "enabled": true, "folder_seats": 999, "a": "', 'the value itself')

# --- backslash and newline come out as they went in
add_host('srv03', {'site_id': 'site3', 'alias': 'back\\\\slash and\\nnewline'})
run()
eq(CheckmkFolderPool.objects.get(name='Pool site3').folder_title,
   'back\\\\slash and\\nnewline', 'special characters')

# --- an ignored host is skipped, the others still get their rule
add_host('srv04', {'site_id': 'site4', 'alias': 'ignored'})
add_host('srv05', {'site_id': 'site5', 'alias': 'next'})
run(ignored=('srv04',))
eq(CheckmkFolderPool.objects(name='Pool site4').count(), 0, 'rule of the ignored host')
eq(CheckmkFolderPool.objects(name='Pool site5').count(), 1, 'rule after the ignored host')

print('AUTORULES_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class AutorulesTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_autorules(self):
        """Values stay values, ignored hosts are skipped."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('AUTORULES_OK', result.stdout)
