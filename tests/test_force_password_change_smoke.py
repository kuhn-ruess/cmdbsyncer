"""
A user who has to change the password gets nowhere else in the web interface,
but can still log in and out, change it, set up 2FA and load static files. The
REST API stays out of it: service users have no way to clear the flag there.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import base64
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
import pyotp

from application import limiter

limiter.enabled = False

NEW_PASSWORD = 'New-Password-2026!x'


def to_change_password(response, what):
    eq(response.status_code, 302, f'answer of {what}')
    eq(response.headers['Location'].endswith('/change-password'), True,
       f'{what} leads to {response.headers["Location"]}')


forced = User(email='forced@example.com', name='forced', global_admin=True,
              api_roles=['all'], force_password_change=True)
forced.set_password('smoke-password')
forced.save()

# --- login is reachable and sends to the form
token = csrf('/login')
to_change_password(client.post('/login', data={
    'login_email': 'forced@example.com', 'password': 'smoke-password', 'otp': '',
    'login_submit': 'Login', 'csrf_token': token}), 'the login')

# --- nothing else is reachable, whatever the method or the path
for url in ('/admin/', '/admin/host/', '/admin/user/', '/set-theme', '/api-tokens', '/'):
    to_change_password(client.get(url), f'GET {url}')
token = csrf('/change-password')
to_change_password(client.post('/admin/user/new/', data={
    'email': 'new@example.com', 'name': 'new', 'csrf_token': token}), 'POST of a form')
eq(User.objects(email='new@example.com').count(), 0, 'user created past the check')
to_change_password(client.post('/set-theme', data={'theme': 'default', 'csrf_token': token}),
                   'POST /set-theme')

# --- the password form renders with everything it needs
page = check('/change-password', 200).get_data(as_text=True)
eq('name="password"' in page, True, 'password field')

# --- so does static content, from every place the pages load it
check('/static/favicon.png', 200)
check('/themes/nord.css', 200)
for url in re.findall(r'(?:href|src)="(/admin/static/[^"?]+)', page):
    check(url, 200)
eq('/admin/static/' in page, True, 'the page loads Flask-Admin static files')

# --- 2FA setup works and leads back to the form
page = check('/set-2fa', 200).get_data(as_text=True)
secret = re.search(r'name="secret"[^>]*value="([^"]+)"', page)
if not secret:
    secret = re.search(r'value="([^"]+)"[^>]*name="secret"', page)
secret = secret.group(1)
token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page).group(1)
response = client.post('/set-2fa', data={'secret': secret, 'otp': pyotp.TOTP(secret).now(),
                                         'csrf_token': token})
eq(response.status_code, 302, 'answer of the 2FA setup')
eq(User.objects.get(email='forced@example.com').tfa_secret, secret, 'the 2FA secret')
to_change_password(client.get(response.headers['Location']), 'the page after the 2FA setup')
User.objects(email='forced@example.com').update(unset__tfa_secret=1)

# --- logout works
check('/logout', 200)
token = csrf('/logout')
response = check('/logout', 302, method='post', data={'csrf_token': token})
eq('/change-password' in response.headers['Location'], False, 'logout goes to the form')
eq(client.get('/set-theme').status_code, 302, 'logged out')
eq('/login' in client.get('/set-theme').headers['Location'], True, 'logged out to the login')

# --- the REST API does not ask, with or without a session
auth = {'Authorization': 'Basic ' + API_AUTH}
check('/api/v1/objects/all', 200, headers=auth)
token = csrf('/login')
client.post('/login', data={'login_email': 'forced@example.com', 'password': 'smoke-password',
                            'otp': '', 'login_submit': 'Login', 'csrf_token': token})
to_change_password(client.get('/admin/host/'), 'GET /admin/host/ after the new login')
check('/api/v1/objects/all', 200, headers=auth)

# --- changing the password ends it
token = csrf('/change-password')
client.post('/change-password', data={'password': NEW_PASSWORD, 'password_repeat': NEW_PASSWORD,
                                      'submit': '1', 'csrf_token': token})
eq(User.objects.get(email='forced@example.com').force_password_change, False, 'the flag')
eq('/change-password' in client.get('/admin/').headers.get('Location', ''), False,
   'start page after the change')
check('/admin/host/', 200)

# --- everyone else never saw any of this
client = app.test_client()
token = csrf('/login')
client.post('/login', data={'login_email': 'smoke@example.com', 'password': 'smoke-password',
                            'otp': '', 'login_submit': 'Login', 'csrf_token': token})
check('/admin/host/', 200)

print('FORCE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class ForcePasswordChangeTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_force_password_change(self):
        """The flag holds on every web page and leaves the API alone."""
        api_auth = base64.b64encode(b'forced@example.com:smoke-password').decode()
        result = run_against_app(f"API_AUTH = '{api_auth}'\n" + SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('FORCE_OK', result.stdout)
