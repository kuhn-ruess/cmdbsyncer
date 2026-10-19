"""
The Secret Store must not hand a restricted user anything outside their
scope.

A user limited to accounts (``restrict_to_accounts``) or CMDB templates
reaches only the hosts inside that limit. For the Secret Store that means:
they only list, edit, bind and reveal entries bound to those hosts, never
a global entry and never another host's secret; not in the web view, not
through the manual import, not through the rule export/import API and not
through a template rendered for them.

These tests boot the real web application against an in-memory database
(see ``tests/web_smoke_helpers.py``) and assert on what really comes back.

Fixture:

    host-a  account-a   secret token (bound)
    host-b  account-b   secret token (bound)
    host-c  account-a   no secret
    global entry  shared-pw
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


FIXTURE = '''
import base64
import io
import re

from application.models.account import Account
from application.models.host import Host
from application.models.secret import Secret, store_host_secret, refresh_orphans

for account_name in ('account-a', 'account-b'):
    Account(name=account_name, type='custom', enabled=True).save()

HOSTS = {}
for hostname, account_name in (('host-a', 'account-a'), ('host-b', 'account-b'),
                               ('host-c', 'account-a')):
    HOSTS[hostname] = Host(hostname=hostname, source_account_name=account_name)
    HOSTS[hostname].save()

SECRET_A = store_host_secret(HOSTS['host-a'], 'token', 'value-of-a', 'fixture')
SECRET_B = store_host_secret(HOSTS['host-b'], 'token', 'value-of-b', 'fixture')
GLOBAL = Secret(name='shared-pw', title='Shared', enabled=True)
GLOBAL.set_password('value-of-global')
GLOBAL.save()


def make_user(email, roles=(), accounts=(), admin=False, api_roles=('all',)):
    person = User(email=email, name=email, global_admin=admin,
                  roles=list(roles), api_roles=list(api_roles),
                  restrict_to_accounts=list(accounts))
    person.set_password('smoke-password')
    person.save()
    return person


make_user('admin@example.com', admin=True)
# Global admin, but limited to account-a: the scope has to bite anyway.
make_user('scoped-admin@example.com', admin=True, accounts=['account-a'])
make_user('scoped-reader@example.com', roles=['secrets', 'secrets_reveal', 'host'],
          accounts=['account-a'])
make_user('manager@example.com', roles=['secrets', 'host'])
make_user('outsider@example.com', roles=['host'])

SESSIONS = {}


def web(email):
    if email in SESSIONS:
        return SESSIONS[email]
    session = app.test_client()
    # One address per user: the login form is rate limited per address,
    # and a refused login would make every later check pass vacuously.
    session.environ_base['REMOTE_ADDR'] = f'192.0.2.{len(SESSIONS) + 10}'
    body = session.get('/login').get_data(as_text=True)
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body).group(1)
    session.post('/login', data={
        'login_email': email, 'password': 'smoke-password', 'otp': '',
        'login_submit': 'Login', 'csrf_token': token,
    })
    if '/login' in (session.get('/admin/').headers.get('Location') or ''):
        fail(f'{email} could not log in')
    SESSIONS[email] = session
    return session


def form_token(email, url):
    body = web(email).get(url).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body)
    if not match:
        fail(f'{email}: no CSRF token at {url}')
    return match.group(1)


def basic(email):
    raw = base64.b64encode(f'{email}:smoke-password'.encode()).decode()
    return {'Authorization': 'Basic ' + raw}


def entry_form(token, **fields):
    data = {'csrf_token': token, 'name': 'x', 'title': 'x', 'owner': 'admin',
            'kind': 'password', 'enabled': 'y', 'export_to_checkmk': 'y',
            'hostname': '', 'key': '', 'password': ''}
    data.update(fields)
    return data
'''


WEB = FIXTURE + '''
# --- the list -------------------------------------------------------------
body = web('admin@example.com').get('/admin/secret/').get_data(as_text=True)
for name in ('host-a:token', 'host-b:token', 'shared-pw'):
    if name not in body:
        fail(f'the unrestricted admin does not see {name}')

for email in ('scoped-admin@example.com', 'scoped-reader@example.com'):
    page = web(email).get('/admin/secret/')
    eq(page.status_code, 200, f'{email} opens the store')
    body = page.get_data(as_text=True)
    if 'host-a:token' not in body:
        fail(f'{email} does not see the secret of its own host')
    for leaked in ('host-b:token', 'shared-pw'):
        if leaked in body:
            fail(f'{email} sees {leaked}, which is outside its scope')

# No store role, no store.
page = web('outsider@example.com').get('/admin/secret/')
if page.status_code == 200 and 'host-a:token' in page.get_data(as_text=True):
    fail('a user without the Secret Store role lists entries')

# --- reading values -------------------------------------------------------
page = web('scoped-reader@example.com').get(f'/admin/secret/reveal?id={SECRET_A.id}')
eq(page.status_code, 200, 'reveal of an own entry with the reveal role')
if 'value-of-a' not in page.get_data(as_text=True):
    fail('reveal does not show the value')

for target in (SECRET_B, GLOBAL):
    page = web('scoped-reader@example.com').get(f'/admin/secret/reveal?id={target.id}')
    eq(page.status_code, 404, f'reveal of {target.name} outside the scope')

# The store role alone does not show plaintext.
page = web('manager@example.com').get(f'/admin/secret/reveal?id={SECRET_A.id}')
if 'value-of-a' in page.get_data(as_text=True):
    fail('reveal works without the reveal role')

# The edit form of a foreign entry must not open either.
page = web('scoped-admin@example.com').get(f'/admin/secret/edit/?id={SECRET_B.id}')
if 'host-b' in page.get_data(as_text=True):
    fail('the edit form of a foreign entry opens')

# --- binding --------------------------------------------------------------
# Rebinding the own entry to a host of another account is refused.
token = form_token('scoped-admin@example.com', f'/admin/secret/edit/?id={SECRET_A.id}')
web('scoped-admin@example.com').post(
    f'/admin/secret/edit/?id={SECRET_A.id}',
    data=entry_form(token, name='host-a:token', hostname='host-b', key='moved'))
SECRET_A.reload()
eq((SECRET_A.hostname, SECRET_A.key), ('host-a', 'token'),
   'binding the own entry to a foreign host')

# Rebinding to another host inside the scope works.
web('scoped-admin@example.com').post(
    f'/admin/secret/edit/?id={SECRET_A.id}',
    data=entry_form(token, name='host-a:token', hostname='host-c', key='token'))
SECRET_A.reload()
eq(SECRET_A.hostname, 'host-c', 'binding the own entry to an own host')
eq(SECRET_A.get_password(), 'value-of-a', 'an empty value field keeps the value')

# New entries: global or for a foreign host are refused, own host works.
token = form_token('scoped-admin@example.com', '/admin/secret/new/')
for name, hostname in (('sneaky-global', ''), ('sneaky-foreign', 'host-b')):
    web('scoped-admin@example.com').post('/admin/secret/new/', data=entry_form(
        token, name=name, hostname=hostname, key='other', password='p'))
    if Secret.objects(key='other').count() or Secret.objects(name=name).count():
        fail(f'a scoped user created {name}')
web('scoped-admin@example.com').post('/admin/secret/new/', data=entry_form(
    token, name='mine', hostname='host-a', key='other', password='p'))
if not Secret.objects(name='host-a:other').count():
    fail('a scoped user cannot create an entry for an own host')

# --- switching entries on and off -------------------------------------------
# The bulk action only switches entries the user lists.
token = form_token('scoped-admin@example.com', '/admin/secret/')
web('scoped-admin@example.com').post('/admin/secret/action/', data={
    'csrf_token': token, 'action': 'disable',
    'rowid': [str(SECRET_A.id), str(SECRET_B.id), str(GLOBAL.id)]})
for entry, expected, what in ((SECRET_A, False, 'its own entry'),
                              (SECRET_B, True, 'a foreign entry'),
                              (GLOBAL, True, 'a global entry')):
    entry.reload()
    eq(bool(entry.enabled), expected, f'bulk disable by a scoped user on {what}')
# The inline switch in the list saves (its form has no binding fields).
token = form_token('admin@example.com', '/admin/secret/')
page = web('admin@example.com').post('/admin/secret/ajax/update/', data={
    'csrf_token': token, 'list_form_pk': str(SECRET_A.id), 'enabled': 'y'})
eq(page.status_code, 200, 'the inline enabled switch saves')
SECRET_A.reload()
eq((SECRET_A.enabled, SECRET_A.hostname), (True, 'host-c'),
   'the inline switch keeps the binding')

# --- orphans --------------------------------------------------------------
HOSTS['host-b'].soft_delete('test')
HOSTS['host-b'].save()
refresh_orphans()
SECRET_B.reload()
eq(SECRET_B.orphaned, True, 'secret of an archived host is orphaned')
eq(Secret.objects(id=SECRET_B.id).count(), 1, 'the orphaned entry is kept')
token = form_token('admin@example.com', f'/admin/secret/edit/?id={SECRET_B.id}')
web('admin@example.com').post(
    f'/admin/secret/edit/?id={SECRET_B.id}',
    data=entry_form(token, name='host-b:token', hostname='host-a', key='token'))
SECRET_B.reload()
# host-a is free again: its entry moved to host-c above.
eq((SECRET_B.hostname, SECRET_B.orphaned), ('host-a', False),
   'an orphaned entry bound to a new host')

# --- the host Overview ------------------------------------------------------
# host-c now holds the former entry of host-a (key token).
def overview(email, hostname):
    host = Host.objects.get(hostname=hostname)
    page = web(email).get(f'/admin/host/details/?id={host.id}')
    return page.status_code, page.get_data(as_text=True)

status, body = overview('admin@example.com', 'host-c')
eq(status, 200, 'the host overview opens')
if "secret(&#39;token&#39;)" not in body and "secret('token')" not in body:
    fail('the host overview does not show the rule reference of its secret')
if 'value-of-a' in body:
    fail('the host overview shows a secret value')
if '/admin/secret/reveal' not in body:
    fail('the host overview offers no way to show the value to an admin')
status, body = overview('scoped-reader@example.com', 'host-c')
if '/admin/secret/reveal' not in body:
    fail('a scoped user with the reveal role gets no show link on an own host')
# The store role alone: keys yes, no show link.
status, body = overview('manager@example.com', 'host-c')
if "secret(" not in body or '/admin/secret/reveal' in body:
    fail('the store role without reveal sees the wrong Secrets row')
# No store role: no secrets row content at all.
status, body = overview('outsider@example.com', 'host-c')
if "secret(" in body:
    fail('a user without the Secret Store role sees the secrets of a host')

print('SECRET_WEB_OK')
'''


API = FIXTURE + '''
def exported(email):
    response = client.get('/api/v1/rules/export?include_passwords=1',
                          headers=basic(email))
    eq(response.status_code, 200, f'{email} rule export')
    return response.json['rules'].get('cmk_passwords', [])

if len(exported('admin@example.com')) != 3:
    fail('the unrestricted export lacks Secret Store entries')
if exported('scoped-admin@example.com'):
    fail('a scoped user exports the Secret Store')

response = client.get('/api/v1/rules/cmk_passwords', headers=basic('scoped-admin@example.com'))
if response.json.get('rules'):
    fail('a scoped user reads the Secret Store by rule type')

# Importing entries (e.g. one bound to a foreign host) is refused.
payload = {'rule_type': 'cmk_passwords', 'rules': [
    {'name': 'planted', 'title': 'planted', 'owner': 'admin',
     'host_id': {'$oid': str(HOSTS['host-b'].id)}, 'key': 'planted'}]}
client.post('/api/v1/rules/import', json=payload,
            headers=basic('scoped-admin@example.com'))
if Secret.objects(name='planted').count():
    fail('a scoped user imported a Secret Store entry')

print('SECRET_API_OK')
'''


JINJA = FIXTURE + '''
from application.helpers.syncer_jinja import render_jinja

# Outside a request: the export, everything resolves for its own host.
eq(render_jinja("{{ secret('token') }}", HOSTNAME='host-a'),
   SECRET_A.checkmk_ident(), 'secret() for the rendered host')
eq(render_jinja("{% set HOSTNAME = 'host-b' %}{{ secret('token') }}",
                HOSTNAME='host-a'),
   SECRET_A.checkmk_ident(), 'a template cannot switch the host')
eq(render_jinja("{{ secret('shared-pw') }}", HOSTNAME='host-a'),
   GLOBAL.checkmk_ident(), 'secret() falls back to the global entry')
eq(render_jinja("{{ cmk_password('host-b:token') }}", HOSTNAME='host-a'),
   'cmdbsyncer_missing_host-b:token', 'cmk_password() never reaches a host entry')
eq(render_jinja("{{ secret_value('token') }}", HOSTNAME='host-a'),
   'value-of-a', 'secret_value() in the export')

# Inside a request the acting user decides.
from flask_login import login_user
for email, expected in (('scoped-reader@example.com', 'value-of-a'),
                        ('manager@example.com', '******')):
    with app.test_request_context('/'):
        login_user(User.objects.get(email=email))
        eq(render_jinja("{{ secret_value('token') }}", HOSTNAME='host-a'),
           expected, f'secret_value() for {email}')
with app.test_request_context('/'):
    login_user(User.objects.get(email='scoped-reader@example.com'))
    eq(render_jinja("{{ secret_value('shared-pw') }}", HOSTNAME='host-a'),
       '******', 'a scoped user never reads a global value')

print('SECRET_JINJA_OK')
'''


IMPORT = FIXTURE + '''
YAML_A = (
    "cluster: host-a\\n"
    "api: https://api.example.com:6443\\n"
    "checkmk_token: imported-token\\n"
    "certificate: |\\n"
    "  -----BEGIN CERTIFICATE-----\\n"
    "  AAAA\\n"
    "  -----END CERTIFICATE-----\\n"
)
YAML_B = YAML_A.replace('host-a', 'host-b').replace('imported-token', 'planted-token')


def preview_rows(email, files=(), pasted=None, paste_format='auto'):
    """Upload `files` (or paste `pasted` into Manual add); the preview rows."""
    import html
    import json as _json
    session = web(email)
    token = form_token(email, '/admin/host/')
    if pasted is None:
        preview = session.post('/admin/host/csv_import', data={
            'csrf_token': token, 'return_to': '/admin/host/',
            'csv_file': [(io.BytesIO(text.encode()), name) for name, text in files],
        }, content_type='multipart/form-data')
    else:
        preview = session.post('/admin/host/bulk_add', data={
            'csrf_token': token, 'return_to': '/admin/host/',
            'hosts_text': pasted, 'paste_format': paste_format,
        })
    body = preview.get_data(as_text=True)
    rows = re.search(r'<textarea name="csv_text"[^>]*>(.*?)</textarea>', body, re.S)
    if not rows:
        fail(f'{email}: no import preview: {body[:300]}')
    return _json.loads(html.unescape(rows.group(1)))


def run_rows(email, rows, secret_columns=(), account='cmdb', hostname_column='cluster',
             template_id=''):
    """Start the import of `rows` as the editable preview sends them."""
    import json as _json
    token = form_token(email, '/admin/host/')
    web(email).post('/admin/host/csv_import_run', data={
        'csrf_token': token, 'return_to': '/admin/host/',
        'csv_text': _json.dumps(rows), 'import_format': 'json',
        'has_header': '1', 'hostname_column': hostname_column,
        'secret_columns': list(secret_columns), 'account': account,
        'template_id': template_id,
    })


def run_import(email, files, secret_columns, pasted=None, account='cmdb'):
    """Upload or paste, then run the import with the preview's rows."""
    run_rows(email, preview_rows(email, files, pasted), secret_columns, account)


# Unrestricted: the secrets land in the store, not in the labels.
run_import('admin@example.com', [('a.yml', YAML_A)], ['checkmk_token', 'certificate'])
entry = Secret.objects(name='host-a:checkmk_token').first()
if entry is None or entry.get_password() != 'imported-token':
    fail('the imported token is not in the Secret Store')
cert = Secret.objects(name='host-a:certificate').first()
if cert is None or cert.kind != 'certificate' or cert.export_to_checkmk:
    fail('the imported certificate is not stored as certificate')
host = Host.objects.get(hostname='host-a')
if 'checkmk_token' in host.labels or 'certificate' in host.labels:
    fail('a secret column became a label')
if host.labels.get('api') != 'https://api.example.com:6443':
    fail('a plain column did not become a label')

# Scoped to account-a: host-b is outside, its secret must not be stored.
run_import('scoped-reader@example.com', [('b.yml', YAML_B)], ['checkmk_token'],
           account='account-a')
if Secret.objects(name='host-b:checkmk_token').count():
    fail('a scoped user stored a secret for a foreign host')

# Several hosts per file: a list of mappings, and documents split by ---.
run_import('admin@example.com', [('list.yml', (
    "- cluster: list-one\\n  checkmk_token: t1\\n"
    "- cluster: list-two\\n  checkmk_token: t2\\n"))], ['checkmk_token'])
for name in ('list-one:checkmk_token', 'list-two:checkmk_token'):
    if not Secret.objects(name=name).count():
        fail(f'a host of a YAML list is missing: {name}')

# Manual add takes pasted YAML with several documents, secrets included.
run_import('admin@example.com', [], ['checkmk_token'], pasted=(
    "cluster: paste-one\\ncheckmk_token: p1\\n---\\n"
    "cluster: paste-two\\ncheckmk_token: p2\\n"))
for name in ('paste-one:checkmk_token', 'paste-two:checkmk_token'):
    if not Secret.objects(name=name).count():
        fail(f'manual add did not store {name}')
if 'checkmk_token' in Host.objects.get(hostname='paste-one').labels:
    fail('manual add turned a secret column into a label')

# Manual add holds the scope like the upload does.
run_import('scoped-reader@example.com', [], ['checkmk_token'], pasted=(
    "cluster: host-b\\ncheckmk_token: planted-by-paste\\n"), account='account-a')
if Secret.objects(name='host-b:checkmk_token').count():
    fail('a scoped user stored a secret for a foreign host through manual add')

print('SECRET_IMPORT_OK')
'''

MANUAL = IMPORT.replace("print('SECRET_IMPORT_OK')", "") + '''
NL, TAB = chr(10), chr(9)
PEM_BODY = NL.join([
    "  -----BEGIN CERTIFICATE-----", "MIIBfirstline", "QUJDREVGR0g=",
    "  -----END CERTIFICATE-----", "  -----BEGIN CERTIFICATE-----",
    "MIIBsecondline", "  -----END CERTIFICATE-----"])
CHAIN = NL.join([
    "-----BEGIN CERTIFICATE-----", "MIIBfirstline", "QUJDREVGR0g=",
    "-----END CERTIFICATE-----", "-----BEGIN CERTIFICATE-----",
    "MIIBsecondline", "-----END CERTIFICATE-----"]) + NL

# YAML-like file: certificate body lines at column 0, two hosts by ---.
LIKE_YAML = NL.join([
    "cluster: ocp-one.example.com", "api: https://api.example.com:6443",
    "checkmk_token: tok-one", "certificate: |", PEM_BODY, "---",
    "cluster: ocp-two.example.com", "api: https://api2.example.com:6443"]) + NL
rows = preview_rows('admin@example.com', [('cluster.yml', LIKE_YAML)])
eq(len(rows), 2, 'hosts of the YAML-like file')
eq(rows[0]['certificate'], CHAIN, 'the certificate chain of the YAML-like file')
eq(rows[0]['api'], 'https://api.example.com:6443', 'URL with port in YAML-like file')
eq(preview_rows('admin@example.com', pasted=LIKE_YAML)[0]['certificate'], CHAIN,
   'the YAML-like paste in auto mode')

# Key/value list: colon, equals and tab, URL ports kept, empty line splits.
KV = NL.join([
    "cluster: kv-one.example.com", "api = https://api.example.com:6443",
    "env" + TAB + "prod", "token: a:b:c", "certificate: |", PEM_BODY, "",
    "cluster=kv-two.example.com", "api: https://api2.example.com:8443"])
rows = preview_rows('admin@example.com', pasted=KV, paste_format='kv')
eq(len(rows), 2, 'hosts of the key/value list')
eq((rows[0]['api'], rows[0]['env'], rows[0]['token']),
   ('https://api.example.com:6443', 'prod', 'a:b:c'), 'key/value separators')
eq(rows[0]['certificate'], CHAIN, 'certificate block in the key/value list')
eq((rows[1]['cluster'], rows[1]['api']),
   ('kv-two.example.com', 'https://api2.example.com:8443'), 'second key/value host')

# Every mode can be forced.
eq(preview_rows('admin@example.com', pasted="host-x.example.com" + NL + "host-y.example.com",
                paste_format='hosts'),
   [{'hostname': 'host-x.example.com'}, {'hostname': 'host-y.example.com'}], 'host list mode')
eq(preview_rows('admin@example.com', pasted="cluster: y-one.example.com" + NL + "---" + NL
                + "cluster: y-two.example.com", paste_format='yaml'),
   [{'cluster': 'y-one.example.com'}, {'cluster': 'y-two.example.com'}], 'YAML mode')
token = form_token('admin@example.com', '/admin/host/')
body = web('admin@example.com').post('/admin/host/bulk_add', data={
    'csrf_token': token, 'return_to': '/admin/host/', 'paste_format': 'csv',
    'hosts_text': "hostname,env" + NL + "csv-one.example.com,prod"}).get_data(as_text=True)
if 'csv-one.example.com' not in body or 'importTable' not in body:
    fail('CSV mode does not open the preview')

# A plain host list only opens the preview, nothing is created yet.
preview_rows('admin@example.com', pasted="list-only.example.com")
if Host.objects(hostname='list-only.example.com').count():
    fail('manual add created a host before the preview was confirmed')

# A broken paste reports a short error inside the modal, never a page.
body = web('admin@example.com').post('/admin/host/bulk_add', data={
    'csrf_token': token, 'return_to': '/admin/host/', 'paste_format': 'yaml',
    'hosts_text': "cluster: a" + NL + "just some words"},
    headers={'X-Requested-With': 'XMLHttpRequest'}).get_data(as_text=True)
if 'line 2' not in body or 'navbar' in body or 'YAMLError' in body or 'scanning' in body:
    fail(f'the preview error is no short message for the modal: {body[:300]}')

# Account: values per host, own template per host, chosen account.
template = Host(hostname='tmpl-x', object_type='template', is_object=True)
template.save()
run_rows('admin@example.com', [
    {'cluster': 'per-one.example.com', 'env': 'prod', '__template__': str(template.id)},
    {'cluster': 'per-two.example.com', 'env': 'test'}], account='account-b')
one = Host.objects.get(hostname='per-one.example.com')
two = Host.objects.get(hostname='per-two.example.com')
eq((one.labels.get('env'), two.labels.get('env')), ('prod', 'test'), 'values per host')
eq([t.id for t in one.cmdb_templates], [template.id], 'template per host')
eq(two.cmdb_templates, [], 'host without own template')
eq((one.source_account_name, two.source_account_name), ('account-b', 'account-b'),
   'the account picked for the import')

# A template id that is no template is refused for that row.
run_rows('admin@example.com', [{'cluster': 'bad-tmpl.example.com',
                                '__template__': str(HOSTS['host-a'].id)}])
if Host.objects(hostname='bad-tmpl.example.com').count():
    fail('a host was created with a forged template')

# A restricted user: only own accounts, forged values refused.
for forged in ('account-b', 'cmdb', 'no-such-account'):
    run_rows('scoped-reader@example.com',
             [{'cluster': f'forged-{forged}.example.com', 'checkmk_token': 'x'}],
             ['checkmk_token'], account=forged)
    if Host.objects(hostname=f'forged-{forged}.example.com').count():
        fail(f'a scoped user imported into {forged}')
run_rows('scoped-reader@example.com',
         [{'cluster': 'own.example.com', 'checkmk_token': 'own-token'}],
         ['checkmk_token'], account='account-a')
own = Host.objects(hostname='own.example.com').first()
if own is None or own.source_account_name != 'account-a':
    fail('a scoped user cannot import into the own account')
if not Secret.objects(name='own.example.com:checkmk_token').count():
    fail('the secret of a host in the own account is not stored')
# The picker only offers the own account.
body = web('scoped-reader@example.com').post('/admin/host/bulk_add', data={
    'csrf_token': form_token('scoped-reader@example.com', '/admin/host/'),
    'return_to': '/admin/host/', 'hosts_text': 'pick.example.com'}).get_data(as_text=True)
picker = re.search(r'<select[^>]*name="account".*?</select>', body, re.S).group(0)
if 'account-b' in picker or 'cmdb' in picker or 'account-a' not in picker:
    fail(f'the account picker offers foreign accounts: {picker}')

# An existing host outside the scope is not overwritten or taken over.
run_rows('scoped-reader@example.com', [{'cluster': 'host-b', 'env': 'hijacked'}],
         account='account-a')
host_b = Host.objects.get(hostname='host-b')
if host_b.labels.get('env') == 'hijacked' or host_b.source_account_name != 'account-b':
    fail('a scoped user overwrote a host outside the scope')

# Manual add: the dialog template is the default for every host and is
# preselected in the preview; a template-restricted user only gets theirs.
allowed = Host(hostname='tmpl-allowed', object_type='template', is_object=True)
allowed.save()
person = User(email='by-template@example.com', name='by-template', roles=['host'],
              restrict_to_templates=['tmpl-allowed'])
person.set_password('smoke-password')
person.save()
page = web('by-template@example.com').get('/admin/host/').get_data(as_text=True)
dialog = re.search(r'<select[^>]*id="bulkAddTemplateId".*?</select>', page, re.S).group(0)
if 'tmpl-allowed' not in dialog or 'tmpl-x' in dialog:
    fail(f'the Manual add template list ignores the template scope: {dialog}')
body = web('admin@example.com').post('/admin/host/bulk_add', data={
    'csrf_token': form_token('admin@example.com', '/admin/host/'),
    'return_to': '/admin/host/', 'hosts_text': 'dflt.example.com',
    'template_id': str(template.id)}).get_data(as_text=True)
if not re.search(r'<option value="%s"\\s+selected' % template.id, body):
    fail('the dialog template is not preselected in the preview')
run_rows('admin@example.com', [{'hostname': 'dflt.example.com'}],
         hostname_column='hostname', template_id=str(template.id))
eq([t.id for t in Host.objects.get(hostname='dflt.example.com').cmdb_templates],
   [template.id], 'the dialog template applies to every host')
# A forged template outside the scope is not assigned.
run_rows('by-template@example.com', [{'hostname': 'forged-tmpl.example.com'},
                                     {'hostname': 'forged-row.example.com',
                                      '__template__': str(template.id)}],
         hostname_column='hostname', template_id=str(template.id))
forged = Host.objects(hostname='forged-tmpl.example.com').first()
if forged is not None and template.id in [t.id for t in forged.cmdb_templates]:
    fail('a template-restricted user assigned a foreign template')
if Host.objects(hostname='forged-row.example.com').count():
    fail('a template-restricted user assigned a foreign template per host')

print('SECRET_MANUAL_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestSecretStoreScope(unittest.TestCase):
    """Secret Store access stays inside the user's scope."""

    def _run(self, snippet, marker, modes=('False', 'True')):
        for cmdb_mode in modes:
            with self.subTest(cmdb_mode=cmdb_mode):
                result = run_against_app(snippet, cmdb_mode)
                self.assertEqual(
                    result.returncode, 0,
                    f"CMDB_MODE={cmdb_mode}:\n{result.stdout}\n{result.stderr}")
                self.assertIn(marker, result.stdout)

    def test_web_view(self):
        """List, reveal, edit, bind and orphans honour scope and roles."""
        self._run(WEB, 'SECRET_WEB_OK')

    def test_rule_api(self):
        """The rule export/import API keeps the store from scoped users."""
        self._run(API, 'SECRET_API_OK', modes=('False',))

    def test_jinja(self):
        """secret() and secret_value() resolve per host and per user."""
        self._run(JINJA, 'SECRET_JINJA_OK', modes=('False',))

    def test_import(self):
        """The manual YAML import stores secrets only inside the scope."""
        # The manual import exists in CMDB mode only.
        self._run(IMPORT, 'SECRET_IMPORT_OK', modes=('True',))

    def test_manual_add(self):
        """Manual add: paste formats, editable values, account and scope."""
        self._run(MANUAL, 'SECRET_MANUAL_OK', modes=('True',))


if __name__ == '__main__':
    unittest.main()
