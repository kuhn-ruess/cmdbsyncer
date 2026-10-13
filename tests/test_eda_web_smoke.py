"""
Event Driven Ansible against the real web application

Creates an event rule through its form, gives two hosts the Checkmk agent
output the rule matches on and lets the sender run with the request to
the event stream replaced: one host must send its event exactly once,
the other none, and the history must show it.
"""
import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


EDA_FLOW = LOGIN + r'''
from unittest.mock import Mock
from application.models.account import Account
from application.models.host import Host
from application.plugins.eda.models import EdaEventLog, EdaEventRule
from application.plugins.eda.sender import EdaSender

check('/admin/edaeventrule/', 200)
check('/admin/edaeventlog/', 200)
check('/admin/module_overview_event_driven_ansible/', 200)
body = check('/admin/account/new/?type=eda', 200).get_data(as_text=True)
if 'auth_prefix' not in body:
    fail('the EDA account form does not offer auth_prefix')
form = '/admin/edaeventrule/new/'
check(form, 200)
check(form, 302, method='post', data={
    'csrf_token': csrf(form),
    'name': 'Register TLS',
    'condition_typ': 'all',
    'sort_field': '0',
    'enabled': 'y',
    'conditions-0-match_type': 'tag',
    'conditions-0-tag_match': 'equal',
    'conditions-0-tag': 'cmk_svc__check_mk_agent_output',
    'conditions-0-value_match': 'in',
    'conditions-0-value': 'TLS is not activated',
    'outcomes-0-event': 'register_agent_tls',
    'outcomes-0-extra_vars': 'os: "{{ os }}"\nport: 8000',
    'outcomes-0-resend_after_hours': '24',
})
eq(EdaEventRule.objects(name='Register TLS').count(), 1, 'saved rules')
check('/admin/edaeventrule/', 200)

account = Account(name='eda', type='eda', enabled=True,
                  address='https://eda.example.com/hook')
account.set_password('tok')
account.save()

for name, output in (('srv01', 'TLS is not activated on monitored host'),
                     ('srv02', 'Version: 2.3.0')):
    host = Host.get_host(name)
    host.update_host({'os': 'linux'})
    host.update_inventory('cmk_svc', {'check_mk_agent_output': output})
    host.save()

sender = EdaSender('eda')
sender.inner_request = Mock(return_value=Mock(status_code=200, text='ok'))
eq(sender.send_events()['sent'], 1, 'events sent')
kwargs = sender.inner_request.call_args.kwargs
eq(kwargs['json']['hostname'], 'srv01', 'host of the event')
eq(kwargs['json']['vars'], {'os': 'linux', 'port': 8000}, 'vars of the event')
eq(kwargs['headers']['Authorization'], 'Bearer tok', 'token header')

again = EdaSender('eda')
again.inner_request = Mock()
eq(again.send_events()['skipped'], 1, 'events skipped on the second run')
eq(again.inner_request.called, False, 'request on the second run')

eq(EdaEventLog.objects(status='success').count(), 1, 'history entries')
check('/admin/edaeventlog/', 200)
print('EDA_FLOW_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestEdaFlow(unittest.TestCase):
    """Rule form, matching and sending work together."""

    def test_event_is_sent_once(self):
        """One matching host, one event, not repeated on the next run."""
        result = run_against_app(EDA_FLOW, 'False')
        self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")
        self.assertIn('EDA_FLOW_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
