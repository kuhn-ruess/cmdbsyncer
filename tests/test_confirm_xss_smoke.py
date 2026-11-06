"""
Names in the confirm dialogs stay data: a saved search called like a piece of
JavaScript doesn't run. Shared searches can't be changed by others, and the
Cancel link of a bulk form doesn't take a javascript: URL.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import html
import json

from application import limiter
from application.models.saved_search import SavedSearch

limiter.enabled = False

EVIL = "');alert(1);//\\"><script>alert(2)</script>"

user.roles = ['host']
user.save()
for email in ('other@example.com', 'third@example.com'):
    new = User(email=email, name=email, roles=['host'])
    new.set_password('smoke-password')
    new.save()


def login(email):
    global client
    client = app.test_client()
    client.post('/login', data={
        'login_email': email, 'password': 'smoke-password',
        'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
    })


login('smoke@example.com')
shared = SavedSearch(name=EVIL, path='/admin/host/', query_string='',
                     owner_email='other@example.com', shared=True)
shared.save()

# --- what the browser hands to JavaScript is one string, the whole name
body = check('/admin/host/', 200).get_data(as_text=True)
matches = re.findall(r"onsubmit='return confirm\\((.*?)\\);'>", body)
eq(len(matches), 1, 'confirm dialogs of a preset')
eq(json.loads(html.unescape(matches[0])), f'Delete preset "{EVIL}"?', 'text of the dialog')
if '<script>alert(2)' in body:
    fail('the name is rendered unescaped')

# --- Cancel of the bulk forms
for form in ('set_account_form', 'assign_project_form', 'bulk_label_form', 'set_template_form'):
    for bad in ('javascript:alert(1)', 'https://evil.example.com/', '//evil.example.com/',
                '/\\\\evil.example.com/'):
        page = client.get(f'/admin/host/{form}', query_string={'ids': 'x', 'return_to': bad})
        eq(page.status_code, 200, f'{form}')
        if html.escape(bad, quote=True) in page.get_data(as_text=True) or \\
                bad in page.get_data(as_text=True):
            fail(f'{form} takes {bad} as return_to')
    page = client.get(f'/admin/host/{form}', query_string={'ids': 'x', 'return_to': '/admin/host/?a=1'})
    eq('/admin/host/?a=1' in html.unescape(page.get_data(as_text=True)), True, f'{form} keeps a list url')

# --- shared: usable by all, changeable by the owner and global admins
edit = f'/admin/saved_searches/edit/?id={shared.id}'
login('third@example.com')
token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"',
                  client.get('/admin/saved_searches/').get_data(as_text=True)).group(1)
client.post(edit, data={'name': 'changed', 'csrf_token': token})
eq(SavedSearch.objects.get(id=shared.id).name, EVIL, 'a shared search changed by another user')
client.post('/admin/saved_searches/delete/', data={'id': str(shared.id), 'csrf_token': token})
eq(SavedSearch.objects(id=shared.id).count(), 1, 'a shared search deleted by another user')
client.post(f'/admin/host/delete_preset/{shared.id}', data={'csrf_token': token})
eq(SavedSearch.objects(id=shared.id).count(), 1, 'a shared preset deleted by another user')

login('other@example.com')
token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"',
                  client.get('/admin/saved_searches/').get_data(as_text=True)).group(1)
client.post(edit, data={'name': 'changed', 'csrf_token': token})
eq(SavedSearch.objects.get(id=shared.id).name, 'changed', 'changed by its owner')

print('CONFIRM_XSS_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class ConfirmXssTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_confirm_xss(self):
        """Names stay data, shared searches stay with their owner."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('CONFIRM_XSS_OK', result.stdout)
