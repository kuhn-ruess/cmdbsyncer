"""
The topics of the Checkmk Configuration Checks page against the real web
application: they fold, export on their own as CSV and PDF, and the topic
of pending service discoveries starts a discovery on the picked hosts.
Checkmk is not contacted, the check and the discovery start are replaced.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SETUP = '''
from application.models.account import Account
from application.plugins.checkmk import config_checks
from application.plugins.checkmk.config_checks import discovery
from application.plugins.checkmk.config_checks.unhandled import UnhandledProblemsCheck

Account(name='cmk-test', type='cmkv2', enabled=True).save()


def service(host, description, state=1, command='check_mk-df'):
    return {'host_name': host, 'description': description, 'state': state,
            'plugin_output': 'out', 'check_command': command, 'acknowledged': 0,
            'scheduled_downtime_depth': 0, 'host_state': 0,
            'host_scheduled_downtime_depth': 0}


class Cmk:
    def request(self, url, method='GET', params=None):
        rows = [] if 'host/' in url else [
            service('srv01', 'Check_MK Discovery', command='check_mk-discovery'),
            service('srv02', 'Check_MK Discovery', command='check_mk-discovery'),
            service('srv01', 'Filesystem /', state=2)]
        return {'value': [{'extensions': row} for row in rows]}, {}


config_checks.run_checks = lambda account, names: [
    UnhandledProblemsCheck().run(Cmk(), account)]
started = []
def fake_run(account, hosts, options, activate, user):
    started.append((account, hosts, options, activate))
    return 'job-1'
discovery.run = fake_run

client.post('/login', data={'login_email': 'smoke@example.com',
                            'password': 'smoke-password', 'otp': '',
                            'login_submit': 'Login', 'csrf_token': csrf('/login')})
base = '/admin/checkmk_config_checks/'
form = {'account': 'cmk-test', 'checks': 'unhandled'}
'''

TOPICS = SETUP + '''
page = check(base + 'run', 200, method='post',
             data={**form, 'csrf_token': csrf(base)}).get_data(as_text=True)
if page.count('<details class="cc-section"') != 4:
    fail('topics do not fold')
if '<details class="cc-section" id="cc-unhandled-hosts" >' not in page:
    fail('empty topic not folded')
if 'id="cc-unhandled-discovery-discovery"' not in page:
    fail('discovery form missing')
for host in ('srv01', 'srv02'):
    if f'name="hosts" value="{host}"' not in page:
        fail(f'no checkbox for {host}')
if page.count('name="format" value="csv"') != 2:
    fail('CSV export not offered per topic with findings')

response = check(base + 'export', 200, method='post', data={
    **form, 'topic': 'discovery', 'format': 'csv', 'csrf_token': csrf(base)})
eq(response.mimetype, 'text/csv', 'csv mimetype')
text = response.get_data(as_text=True)
eq(text.splitlines()[:2], ['\\ufeffsep=;', 'Host;State;Output'], 'csv head')
if 'srv02;WARN;out' not in text or 'Filesystem' in text:
    fail('csv rows: ' + repr(text))
if 'unhandled-discovery' not in response.headers['Content-Disposition']:
    fail('csv name ' + response.headers['Content-Disposition'])

answer = client.post(base + 'discovery', data={
    'account': 'cmk-test', 'hosts': ['srv02', 'srv01', 'srv02'],
    'monitor_undecided_services': '1', 'activate': '1',
    'csrf_token': csrf(base)}).get_json()
if not answer['ok'] or 'job-1' not in answer['message']:
    fail('discovery answer ' + repr(answer))
eq(started, [('cmk-test', ['srv02', 'srv01'], ['monitor_undecided_services'], True)],
   'discovery start')
answer = client.post(base + 'discovery', data={
    'account': 'cmk-other', 'hosts': ['srv01'], 'csrf_token': csrf(base)}).get_json()
if answer['ok']:
    fail('discovery on an account the user may not pick')

# Only the data quality role: the page, but no discovery
user.global_admin = False
user.roles = ['checkmk_data_quality']
user.save()
page = check(base + 'run', 200, method='post',
             data={**form, 'csrf_token': csrf(base)}).get_data(as_text=True)
if 'cc-discovery' in page.split('<script>')[0]:
    fail('discovery offered without the Checkmk right')
answer = client.post(base + 'discovery', data={
    'account': 'cmk-test', 'hosts': ['srv01'], 'csrf_token': csrf(base)}).get_json()
if answer['ok'] or len(started) != 1:
    fail('discovery started without the Checkmk right')
print('TOPICS_OK')
'''

TOPIC_PDF = SETUP + '''
response = check(base + 'export', 200, method='post', data={
    **form, 'topic': 'discovery', 'format': 'pdf', 'csrf_token': csrf(base)})
eq(response.mimetype, 'application/pdf', 'pdf mimetype')
eq(response.data[:5], b'%PDF-', 'PDF header')
print('TOPIC_PDF_OK')
'''

try:
    import fpdf  # noqa: F401  pylint: disable=unused-import
    HAVE_FPDF = True
except ImportError:
    HAVE_FPDF = False


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class ConfigChecksTopicsTests(unittest.TestCase):
    """Runs the snippets against the booted app."""

    def _run(self, snippet, marker):
        result = run_against_app(snippet, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        self.assertIn(marker, result.stdout)

    def test_topics_fold_export_and_discover(self):
        """Fold, CSV per topic, discovery with rights."""
        self._run(TOPICS, 'TOPICS_OK')

    def test_csv_without_fpdf(self):
        """The CSV export of a topic does not need fpdf2."""
        self._run("import sys\nsys.modules['fpdf'] = None\n" + TOPICS, 'TOPICS_OK')

    @unittest.skipUnless(HAVE_FPDF, 'fpdf2 not installed')
    def test_topic_pdf(self):
        """One topic as PDF."""
        self._run(TOPIC_PDF, 'TOPIC_PDF_OK')


if __name__ == '__main__':
    unittest.main()
