"""
Critical labels wait for a second operator, whichever form they are changed
in. Without APPROVAL_REQUIRED_LABELS everything works as if it didn't exist.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application import limiter
from application.models.field_approval import FieldApproval
from application.models.host import Host

limiter.enabled = False
sessions = {}


def login(email):
    global client, TOKEN
    if email in sessions:
        client, TOKEN = sessions[email]
        return
    if not User.objects(email=email):
        new = User(email=email, name=email, roles=['host', 'approval'])
        new.set_password('smoke-password')
        new.save()
    client = app.test_client()
    client.post('/login', data={
        'login_email': email, 'password': 'smoke-password',
        'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
    })
    TOKEN = csrf('/set-theme')
    sessions[email] = (client, TOKEN)


host = Host(hostname='h1', source_account_id='cmdb', source_account_name='cmdb',
            labels={'critical': 'old', 'plain': 'old'})
host.save()


def label(key):
    return Host.objects.get(id=host.id).get_labels().get(key)


def bulk_edit(mode, key, value='', new_key=''):
    client.post('/admin/host/bulk_label_process', data={
        'host_ids': str(host.id), 'mode': mode, 'label_key': key, 'label_value': value,
        'new_key': new_key, 'csrf_token': TOKEN})


def decide(action, approval):
    client.post('/admin/fieldapproval/action/', data={
        'action': action, 'rowid': [str(approval.id)],
        'url': '/admin/fieldapproval/', 'csrf_token': TOKEN})
    return FieldApproval.objects.get(id=approval.id)


# --- without the setting: nothing waits, no queue
login('alice@example.com')
bulk_edit('add', 'critical', 'direct')
eq(label('critical'), 'direct', 'label without the setting')
eq(FieldApproval.objects.count(), 0, 'queue without the setting')
eq(client.get('/admin/fieldapproval/').status_code, 403, 'queue page without the setting')

app.config['APPROVAL_REQUIRED_LABELS'] = ['critical']

# --- with it: the critical label waits, the rest goes through
bulk_edit('add', 'critical', 'wanted')
eq(label('critical'), 'direct', 'critical label before the approval')
bulk_edit('add', 'plain', 'new')
eq(label('plain'), 'new', 'a plain label is changed right away')
eq(FieldApproval.objects.count(), 1, 'queued changes')
approval = FieldApproval.objects.first()
eq(approval.new_value, 'wanted', 'the requested value')
eq(approval.requested_by_email, 'alice@example.com', 'who asked')

bulk_edit('remove', 'critical')
eq(label('critical'), 'direct', 'critical label after a bulk remove')
bulk_edit('rename', 'critical', new_key='renamed')
eq(label('critical'), 'direct', 'critical label after a bulk rename')
eq(FieldApproval.objects(status='pending').count(), 3, 'all three wait')
FieldApproval.objects(id__ne=approval.id).delete()

# --- not your own
approval = decide('approve', approval)
eq(approval.status, 'pending', 'approving your own change')
eq(label('critical'), 'direct', 'label after approving your own')

# --- but somebody else's
login('bob@example.com')
approval = decide('approve', approval)
eq(approval.status, 'approved', 'approval by a second operator')
eq(label('critical'), 'wanted', 'label after the approval')

# --- withdrawing your own stays possible
login('alice@example.com')
bulk_edit('add', 'critical', 'again')
approval = FieldApproval.objects(status='pending').first()
approval = decide('reject', approval)
eq(approval.status, 'rejected', 'withdrawing your own change')

# --- global admins and approval_bypass don't queue
login('smoke@example.com')
bulk_edit('add', 'critical', 'by-admin')
eq(label('critical'), 'by-admin', 'a global admin changes it right away')

print('APPROVAL_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class LabelApprovalTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_approval(self):
        """Bulk edit honours the queue, nobody approves their own change."""
        result = run_against_app(SNIPPET, True)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('APPROVAL_OK', result.stdout)
