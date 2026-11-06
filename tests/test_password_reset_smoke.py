"""
A password reset doesn't log in, a disabled user neither gets a mail nor keeps
a session, and PUBLIC_URL fixes the address in the reset link.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from unittest.mock import patch

import pyotp

from application import limiter
from application.auth import views

limiter.enabled = False

def make_user(email, **fields):
    new = User(email=email, name=email, roles=['host'], **fields)
    new.set_password('smoke-password')
    new.save()
    return new


TFA = pyotp.random_base32()
victim = make_user('victim@example.com', tfa_secret=TFA)
disabled = make_user('disabled@example.com', disabled=True)
active = make_user('active@example.com')


def ask_for_mail(email, host='localhost'):
    """The reset links the mail would carry"""
    global client
    client = app.test_client()
    # Same host for both requests, the session cookie is bound to it
    body = client.get('/request-password', headers={'Host': host}).get_data(as_text=True)
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body).group(1)
    with patch.object(views, 'send_email') as send:
        client.post('/request-password',
                    data={'request_email': email, 'request_submit': '1', 'csrf_token': token},
                    headers={'Host': host})
    return [call.kwargs['reset_url'] for call in send.call_args_list]


def logged_in():
    return client.get('/set-theme').status_code == 200


# --- the link follows the Host header unless PUBLIC_URL is set
links = ask_for_mail('victim@example.com', host='evil.example.com')
eq(len(links), 1, 'mails for a normal user')
eq(links[0].startswith('http://evil.example.com/'), True, f'default link {links[0]}')
app.config['PUBLIC_URL'] = 'https://syncer.example.com/'
links = ask_for_mail('victim@example.com', host='evil.example.com')
eq(links[0].startswith('https://syncer.example.com/reset-password/'), True,
   f'link with PUBLIC_URL {links[0]}')
app.config['PUBLIC_URL'] = ''

# --- the mail template renders the link it gets
with app.test_request_context():
    html = render_template('email/resetpassword.html', user=victim, reset_url='https://x/y')
eq('href="https://x/y"' in html, True, 'link in the mail')

# --- a reset changes the password and doesn't log in
path = '/' + links[0].split('/', 3)[3]
client = app.test_client()
token = csrf(path)
response = client.post(path, data={'password': 'New-Password-2026!x', 'password_repeat': 'New-Password-2026!x',
                                   'submit': '1', 'csrf_token': token})
victim.reload()
eq(victim.check_password('New-Password-2026!x'), True, 'the new password')
eq(response.status_code, 302, 'answer of the reset')
eq('/login' in response.headers['Location'], True, f'goes to {response.headers["Location"]}')
eq(logged_in(), False, 'logged in after the reset')

# --- so the second factor still applies
token = csrf('/login')
client.post('/login', data={'login_email': 'victim@example.com', 'password': 'New-Password-2026!x',
                            'otp': '000000', 'login_submit': 'Login', 'csrf_token': token})
eq(logged_in(), False, 'logged in with a wrong second factor')
token = csrf('/login')
client.post('/login', data={'login_email': 'victim@example.com', 'password': 'New-Password-2026!x',
                            'otp': pyotp.TOTP(TFA).now(), 'login_submit': 'Login',
                            'csrf_token': token})
eq(logged_in(), True, 'logged in with the second factor')

# --- disabled: no mail, no old link
eq(ask_for_mail('disabled@example.com'), [], 'mail for a disabled user')
eq(ask_for_mail('nobody@example.com'), [], 'mail for an unknown user')
active_link = ask_for_mail('active@example.com')[0]
User.objects(email='active@example.com').update(set__disabled=True)
client = app.test_client()
response = client.get('/' + active_link.split('/', 3)[3])
eq(response.status_code, 302, 'old link of a user disabled meanwhile')
User.objects(email='active@example.com').update(set__disabled=False)

# --- disabling ends a running session
client = app.test_client()
token = csrf('/login')
client.post('/login', data={'login_email': 'active@example.com', 'password': 'smoke-password',
                            'otp': '', 'login_submit': 'Login', 'csrf_token': token})
eq(logged_in(), True, 'logged in')
User.objects(email='active@example.com').update(set__disabled=True)
eq(logged_in(), False, 'session after disabling')

print('RESET_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class PasswordResetTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_reset(self):
        """No login after a reset, no way around the disabled flag."""
        result = run_against_app('from flask import render_template\n' + SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('RESET_OK', result.stdout)
