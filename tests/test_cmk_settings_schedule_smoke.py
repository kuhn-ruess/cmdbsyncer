"""
The weekly schedule of the Checkmk Settings: saved by the form, shown in
the list, run by the cron job with the real models.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from datetime import datetime
from unittest.mock import patch
from application import cron_register
from application.plugins.checkmk.models import CheckmkSettings, CheckmkSite
from application.plugins.checkmk import server_schedule

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})
url = '/admin/checkmksettings/new/'
form = client.get(url).get_data(as_text=True)
for text in ('No schedule', 'Check for new version', 'Install and update the sites'):
    if text not in form:
        fail('form misses ' + text)
client.post(url, data={'name': 'Manual', 'cmk_version': '2.4.0p12',
                       'enabled': 'y', 'schedule_weekday': '',
                       'schedule_hour': '0', 'csrf_token': csrf(url)},
            follow_redirects=True)
manual = CheckmkSettings.objects(name='Manual').first()
if manual is None or manual.schedule_weekday is not None:
    fail('no schedule not saved: ' + repr(manual and manual.schedule_weekday))
client.post(url, data={
    'name': 'Prod', 'cmk_version': '2.4.0p12', 'enabled': 'y',
    'schedule_weekday': 'tue', 'schedule_hour': '22',
    'schedule_update_version': 'y', 'schedule_run_playbook': 'y',
    'csrf_token': csrf(url)}, follow_redirects=True)
entry = CheckmkSettings.objects(name='Prod').first()
if entry is None or entry.schedule_weekday != 'tue' or entry.schedule_hour != '22':
    fail('schedule not saved')
page = client.get('/admin/checkmksettings/').get_data(as_text=True)
if 'Tue 22:00: Version check, Install' not in page:
    fail('list does not show the schedule')
if cron_register.get('Checkmk Server: Scheduled Updates') is not \\
        server_schedule.run_scheduled_updates:
    fail('cron job not registered')

CheckmkSite(name='prod', server_address='srv01', settings_master=entry,
            enabled=True).save()
calls = []
def fake_run(playbook, **kwargs):
    calls.append(kwargs)
    return type('Stats', (), {'pk': '0' * 24, 'status': 'success'})()
majors = [{'major': '2.4.0', 'version': '2.4.0p15'}]
tuesday = datetime(2026, 11, 10, 22, 30)
with patch.object(server_schedule.download_catalog, 'fetch', return_value=majors), \\
        patch.object(server_schedule, 'run_playbook', fake_run), \\
        patch.object(server_schedule, 'datetime') as clock:
    clock.now.return_value = tuesday
    server_schedule.run_scheduled_updates()
    server_schedule.run_scheduled_updates()
entry.reload()
if entry.cmk_version != '2.4.0p15':
    fail('version not set: ' + str(entry.cmk_version))
if entry.schedule_last_run != tuesday:
    fail('last run not stored')
if [c['target_host'] for c in calls] != ['srv01']:
    fail('playbook runs: ' + repr(calls))
if entry.schedule_last_status != 'success' or entry.schedule_last_version != '2.4.0p15':
    fail('result not stored: ' + repr(entry.schedule_last_status))
from application.modules.log.models import LogEntry
if not LogEntry.objects(source='Checkmk Server', message='Weekly run of Prod: success'):
    fail('success not logged')

# Prod after Manual: Manual never succeeded, so Prod is skipped next week
edit_url = f'/admin/checkmksettings/edit/?id={entry.id}'
client.post(edit_url, data={
    'name': 'Prod', 'cmk_version': '2.4.0p15', 'enabled': 'y',
    'schedule_weekday': 'tue', 'schedule_hour': '22',
    'schedule_update_version': 'y', 'schedule_run_playbook': 'y',
    'schedule_depends_on': str(manual.id),
    'csrf_token': csrf(edit_url)}, follow_redirects=True)
entry.reload()
if entry.schedule_depends_on != manual:
    fail('dependency not saved')
manual_url = f'/admin/checkmksettings/edit/?id={manual.id}'
body = client.post(manual_url, data={
    'name': 'Manual', 'cmk_version': '2.4.0p12', 'enabled': 'y',
    'schedule_weekday': '', 'schedule_hour': '0',
    'schedule_depends_on': str(entry.id),
    'csrf_token': csrf(manual_url)}, follow_redirects=True).get_data(as_text=True)
manual.reload()
if manual.schedule_depends_on is not None or 'depends on itself' not in body:
    fail('cycle not refused')
with patch.object(server_schedule, 'run_playbook', fake_run), \
        patch.object(server_schedule, 'datetime') as clock:
    clock.now.return_value = datetime(2026, 11, 17, 22, 30)
    server_schedule.run_scheduled_updates()
entry.reload()
if len(calls) != 1 or entry.schedule_last_status != 'skipped':
    fail('prod not skipped: ' + repr(entry.schedule_last_status))
skipped = LogEntry.objects(source='Checkmk Server',
                           message='Weekly run of Prod: skipped').first()
if skipped is None or not skipped.has_error:
    fail('skip not logged as error')
page = client.get('/admin/checkmksettings/').get_data(as_text=True)
if 'after success of Manual' not in page or 'Last: skipped' not in page:
    fail('list does not show dependency and last run')
print('SCHEDULE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class CmkSettingsScheduleTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_schedule(self):
        """Labelled, saved, listed, run once on its day."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        self.assertIn('SCHEDULE_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
