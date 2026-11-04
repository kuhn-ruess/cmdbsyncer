"""
The Run button of a cron group on the dashboard posts in the background: the
endpoint has to answer with JSON instead of redirecting back to the page.

Runs against the real app like ``tests/test_web_requests_smoke.py``, see
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


TRIGGER_CRON = LOGIN + '''
from application.models.cron import CronGroup

CronGroup(name='smoke-on', enabled=True, interval='hour').save()
CronGroup(name='smoke-off', enabled=False, interval='hour').save()

# A fresh installation is redirected to First Steps instead of the dashboard
check('/admin/first_steps/dismiss', 302, method='post', data={
    'csrf_token': csrf('/admin/first_steps/'),
})
if 'cron-trigger-form' not in check('/admin/', 200).get_data(as_text=True):
    fail('the dashboard does not offer the Run button')


def trigger(group, expected):
    """Post the Run button of `group`, return the message of the answer."""
    response = check('/admin/trigger_cron', expected, method='post', data={
        'group': group, 'csrf_token': csrf('/admin/'),
    })
    eq(response.mimetype, 'application/json', f'answer type for {group}')
    return response.get_json()['message']


if 'smoke-on' not in trigger('smoke-on', 200):
    fail('the answer does not name the scheduled group')
eq(CronGroup.objects.get(name='smoke-on').run_once_next, True, 'enabled group')

if 'disabled' not in trigger('smoke-off', 409):
    fail('the answer does not say the group is disabled')
eq(CronGroup.objects.get(name='smoke-off').run_once_next, False, 'disabled group')

trigger('smoke-missing', 404)
print('TRIGGER_CRON_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestWebCronTrigger(unittest.TestCase):
    """Queueing a cron group from the dashboard."""

    def test_trigger_answers_json(self):
        """Queued, disabled and unknown groups each get a JSON answer."""
        result = run_against_app(TRIGGER_CRON, 'False')
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertIn('TRIGGER_CRON_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
