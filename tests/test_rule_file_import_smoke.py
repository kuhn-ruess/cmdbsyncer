"""
The rule views take a pasted rules file or the path of one next to the export.
What the export writes comes back unchanged for every rule type, a bad file
writes nothing, and a path only reaches regular rule files in the Files folder.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


PREAMBLE = r'''
import json
import os
import tempfile
from datetime import datetime

from mongoengine import fields as mongo_fields

from application import admin, limiter
from application.models.host import Host
from application.models.lookup_table import LookupTable
from application.models.user import User
from application.modules.custom_attributes.models import CustomAttributeRule
from application.plugins.checkmk.models import (
    CheckmkInventorizeAttributes, CheckmkRewriteAttributeRule, CheckmkServiceLabelRule)
from application.plugins.netbox.models import NetboxRewriteAttributeRule
from application.plugins.rules import rule_file_import

limiter.enabled = False


def login(the_client, email, password):
    token_page = the_client.get('/login').get_data(as_text=True)
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', token_page).group(1)
    the_client.post('/login', data={
        'login_email': email, 'password': password, 'otp': '',
        'login_submit': 'Login', 'csrf_token': token,
    })


login(client, 'smoke@example.com', 'smoke-password')

LABELS = '/admin/checkmkservicelabelrule/'
ATTRIBUTES = '/admin/customattributerule/'
REWRITE = None
for _view in admin._views:
    if getattr(_view, 'model', None) is CheckmkRewriteAttributeRule:
        REWRITE = _view.url + '/'


def form_token(base, the_client=None):
    body = (the_client or client).get(base + 'rule_import/').get_data(as_text=True)
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body).group(1)


def post(base, action='import', the_client=None, **data):
    """Submit the import form, answers with the page as text."""
    data.update(action=action, csrf_token=form_token(base, the_client))
    response = (the_client or client).post(base + 'rule_import/', data=data)
    eq(response.status_code, 200, f'POST {base}')
    return response.get_data(as_text=True)


def label_rule(name, **extra):
    return {'name': name, 'enabled': True, 'condition_typ': 'anyway',
            'outcomes': [{'service_pattern': '^Port', 'label_name': 'role',
                          'label_value': '{{ HOSTNAME }}'}], **extra}


def lines(*rules):
    return "\n".join(json.dumps(rule) for rule in rules)


def shown(body):
    """The messages of the page, for a failure to quote."""
    start = body.find('rule_import_')
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', body[start:start + 6000]))[:1500]
'''

ROUND_TRIP = r'''
def sample(field, unique_text):
    """A value for one field, to fill every field of a document."""
    if field.choices:
        choice = field.choices[0]
        return choice[0] if isinstance(choice, (list, tuple)) else choice
    if isinstance(field, mongo_fields.EmbeddedDocumentField):
        return fill(field.document_type(), unique_text)
    if isinstance(field, mongo_fields.ListField):
        if field.field is None:
            return []
        return [sample(field.field, unique_text)]
    if isinstance(field, mongo_fields.ReferenceField):
        return fill(field.document_type(), f'{unique_text} ref').save(validate=False)
    if isinstance(field, mongo_fields.BooleanField):
        return True
    if isinstance(field, (mongo_fields.IntField, mongo_fields.FloatField)):
        return 1
    if isinstance(field, mongo_fields.DateTimeField):
        return datetime(2026, 1, 2, 3, 4, 5)
    if isinstance(field, (mongo_fields.DictField, mongo_fields.MapField)):
        return {}
    if isinstance(field, mongo_fields.EmailField):
        return 'someone@example.com'
    if isinstance(field, mongo_fields.URLField):
        return 'https://example.com/'
    if isinstance(field, mongo_fields.StringField):
        return unique_text
    return None


def fill(document, unique_text):
    for name, field in document._fields.items():
        if name == 'id':
            continue
        # A reference to its own type would fill without end
        if isinstance(field, mongo_fields.ReferenceField) \
                and field.document_type is type(document):
            continue
        value = sample(field, unique_text)
        if value is not None:
            setattr(document, name, value)
    return document


def stored(model):
    return {str(doc.pk): json.loads(doc.to_json()) for doc in model.objects}


seen = 0
for view in admin._views:
    if not getattr(view, 'export_types', None) or 'syncer_rules' not in view.export_types:
        continue
    base = view.url + '/'
    if view.model is Host:
        # Hosts, objects and templates are no rule type of their own. The
        # template view answers with a redirect outside of CMDB mode.
        with app.test_request_context():
            eq(view.rule_file_type, None, 'Host views')
        check(base + 'rule_import/', 302 if 'Templates' in base else 404)
        continue
    with app.test_request_context():
        eq(bool(view.rule_file_type), True, f'{base} has a rule type')
    seen += 1

    sample_rule = fill(view.model(), f'{view.model.__name__} sample')
    if view.model is LookupTable:
        sample_rule.entries = 'location;datacenter\nsite-a;DC1'
    sample_rule.save(validate=False)
    original = stored(view.model)

    listing = check(base, 200).get_data(as_text=True)
    if base + 'rule_import/' not in listing:
        fail(f'{base}: no import in the list')

    response = check(base + 'export/syncer_rules/', 200)
    name = response.headers['Content-Disposition'].split('filename=')[1]
    if not re.fullmatch(rf'{view.model.__name__}_\d+\.syncer_json', name):
        fail(f'{base}: export file named {name}')
    exported = response.get_data(as_text=True)
    header = json.loads(exported.splitlines()[0])
    eq(list(header), ['rule_type'], f'{base}: first line of the export')

    # Paste it back, unchanged: the rule exists
    body = post(base, 'check', rules_text=exported)
    eq(stored(view.model), original, f'{base}: check writes nothing')
    if 'Check passed' not in body:
        fail(f'{base}: check refused its own export: {shown(body)}')
    if 'Skipped, already exists' not in body:
        fail(f'{base}: existing rule not shown')

    post(base, rules_text=exported)
    eq(stored(view.model), original, f'{base}: rule skipped')

    post(base, rules_text=exported, override='1')
    eq(stored(view.model), original, f'{base}: replaced by itself')

    # Into an empty collection
    view.model.objects.delete()
    body = post(base, rules_text=exported)
    if 'Import finished' not in body:
        fail(f'{base}: import of its own export: {shown(body)}')
    eq(stored(view.model), original, f'{base}: round trip')
    view.model.objects.delete()

eq(seen > 30, True, 'rule views covered')
'''

BEHAVIOUR = r'''
# Without _id, as written by hand, and the second time it exists
body = post(LABELS, rules_text=lines(label_rule('hand'), label_rule('hand2')))
eq(sorted(x.name for x in CheckmkServiceLabelRule.objects), ['hand', 'hand2'], 'no _id')
if 'does not name its rule type' not in body and 'Import finished' not in body:
    fail('hand written rules')
body = post(LABELS, rules_text=lines(label_rule('hand')))
eq(CheckmkServiceLabelRule.objects.count(), 2, 'not imported twice')
if 'Skipped, already exists' not in body:
    fail('skipped rule not named')

# Replace only with the option, and it says so
changed = label_rule('hand', documentation='new')
post(LABELS, rules_text=lines(changed))
eq(CheckmkServiceLabelRule.objects(name='hand').first().documentation, None, 'no silent replace')
body = post(LABELS, 'check', rules_text=lines(changed), override='1')
if 'Replaces' not in body:
    fail('the check does not announce the replace')
eq(CheckmkServiceLabelRule.objects(name='hand').first().documentation, None, 'check changed it')
body = post(LABELS, rules_text=lines(changed), override='1')
eq(CheckmkServiceLabelRule.objects(name='hand').first().documentation, 'new', 'replaced')
if 'Replaced' not in body:
    fail('result does not name the replaced rule')
CheckmkServiceLabelRule.objects.delete()

# Some rule types have no unique name: the name counts there as well
rewrite_page = next(v.url + '/' for v in admin._views
                    if getattr(v, 'model', None) is NetboxRewriteAttributeRule)
post(rewrite_page, rules_text=lines({'name': 'same', 'enabled': True}))
post(rewrite_page, rules_text=lines({'name': 'same', 'enabled': False}))
eq([x.enabled for x in NetboxRewriteAttributeRule.objects], [True], 'name counts, skipped')
post(rewrite_page, rules_text=lines({'name': 'same', 'enabled': False}), override='1')
eq([x.enabled for x in NetboxRewriteAttributeRule.objects], [False], 'name counts, replaced')
NetboxRewriteAttributeRule.objects.delete()

# The database failing halfway: the page says exactly what got in
real_save = rule_file_import._save_rule


def fails_on_second(raw, model, **kwargs):
    if raw['name'] == 'second':
        raise OSError('database gone')
    return real_save(raw, model, **kwargs)


rule_file_import._save_rule = fails_on_second
body = post(LABELS, rules_text=lines(label_rule('first'), label_rule('second'), label_rule('third')))
rule_file_import._save_rule = real_save
eq(sorted(x.name for x in CheckmkServiceLabelRule.objects), ['first', 'third'], 'halfway')
if 'Failed, not imported: 1' not in body or 'Imported: 2' not in body:
    fail(f'result after a failure: {shown(body)}')
CheckmkServiceLabelRule.objects.delete()

# All or nothing, with the reason per record


def refused(base, model, text, *expected, **data):
    before = model.objects.count()
    body = post(base, rules_text=text, **data)
    eq(model.objects.count(), before, f'written despite: {expected}')
    if 'Import finished' in body:
        fail(f'accepted: {expected}')
    for part in expected:
        if part not in body:
            fail(f'{part!r} missing in {shown(body)}')


GOOD = json.dumps(label_rule('good'))
refused(LABELS, CheckmkServiceLabelRule, GOOD + '\n{broken', 'Line 2: not valid JSON')
refused(LABELS, CheckmkServiceLabelRule, '{\n"name": "x",\n}', 'Not valid JSON')
refused(LABELS, CheckmkServiceLabelRule, '[' * 50000 + ']' * 50000, 'not a JSON object')
refused(LABELS, CheckmkServiceLabelRule, '[1, 2]', 'not a JSON object')
refused(LABELS, CheckmkServiceLabelRule, '   ', 'nothing to import')
refused(LABELS, CheckmkServiceLabelRule, lines(label_rule('good'), {'name': 'odd', 'typo': 1}),
        'Unknown field(s) for this rule type: typo')
nested = label_rule('nested')
nested['outcomes'][0]['typo'] = 1
refused(LABELS, CheckmkServiceLabelRule, lines(nested), 'outcomes.0.typo')
refused(LABELS, CheckmkServiceLabelRule, lines({'enabled': True}), 'name')
refused(LABELS, CheckmkServiceLabelRule, lines(label_rule('good'), label_rule('good')),
        'Same id or name as Line 1')
refused(LABELS, CheckmkServiceLabelRule, lines(label_rule('id', _id={'$oid': 'nope'})),
        'Not a valid rule')

# The checks of the form hold for an import as well
bad_regex = label_rule('bad_regex')
bad_regex['outcomes'][0]['service_pattern'] = '('
refused(LABELS, CheckmkServiceLabelRule, lines(bad_regex), 'Service Pattern')
bad_jinja = label_rule('bad_jinja')
bad_jinja['outcomes'][0]['label_value'] = '{{ HOSTNAME'
refused(LABELS, CheckmkServiceLabelRule, lines(bad_jinja), 'Jinja in')
# and no markup comes through
refused(LABELS, CheckmkServiceLabelRule, lines({'name': 'x', 'typo<script>': 1}), 'typo&lt;script&gt;')

# Another rule type stays out, even with the same fields
rewrite = {'name': 'same fields', 'enabled': True}
refused(REWRITE, CheckmkRewriteAttributeRule,
        '{"rule_type": "netbox_rewrites"}\n' + lines(rewrite), 'netbox_rewrites')
refused(LABELS, CheckmkServiceLabelRule,
        json.dumps({'rules': {'custom_attributes': [label_rule('x')]}}), 'custom_attributes')
refused(LABELS, CheckmkServiceLabelRule,
        '{"rule_type": "cmk_service_labels"}\n' + GOOD + '\n{"rule_type": "cmk_filter"}\n',
        'cmk_filter')
refused(LABELS, CheckmkServiceLabelRule, '{"rule_type": "<b>x"}\n' + GOOD, 'an unknown type')

# Forms of an export which are fine
post(LABELS, rules_text=json.dumps([label_rule('a_list')]))
post(LABELS, rules_text=json.dumps({'rule_type': 'cmk_service_labels',
                                    'rules': [label_rule('a_bundle')]}))
post(LABELS, rules_text=json.dumps({'rules': {'cmk_service_labels': [label_rule('a_group')]}}))
post(LABELS, rules_text='﻿' + json.dumps(label_rule('a_rule')) + '   ')
eq(sorted(x.name for x in CheckmkServiceLabelRule.objects),
   ['a_bundle', 'a_group', 'a_list', 'a_rule'], 'forms of an export')
CheckmkServiceLabelRule.objects.delete()

# As after a save: the outcomes cached on hosts are dropped, not by a check
host = Host(hostname='srv01', source_account_id='acc', source_account_name='acc')
host.labels = {}
host.inventory = {}
host.cache = {'SomeOutcome': {'x': 1}}
host.save()
post(LABELS, 'check', rules_text=GOOD)
eq(Host.objects(hostname='srv01').first().cache != {}, True, 'check keeps the cache')
post(LABELS, rules_text=GOOD)
eq(Host.objects(hostname='srv01').first().cache, {}, 'import drops the cache')
CheckmkServiceLabelRule.objects.delete()

# ---------- The path ----------
root = tempfile.mkdtemp()
outside = tempfile.mkdtemp()
app.config['FILEADMIN_PATH'] = root
os.mkdir(os.path.join(root, 'sub'))


def place(folder, name, content):
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(content)
    return path


SECRET = 'file-content-marker'
place(root, 'rules.jsonl', GOOD)
place(os.path.join(root, 'sub'), 'CheckmkServiceLabelRule_202601010000.syncer_json',
      json.dumps(label_rule('from_sub')))
place(root, 'other.jsonl', '{"rule_type": "cmk_filter"}\n' + GOOD)
place(root, 'CheckmkFilterRule_202601010000.syncer_json', GOOD)
place(root, 'cmk_filter.json', '[' + GOOD + ']')
place(root, 'notes.txt', GOOD)
place(root, 'content.json', '{"' + SECRET + '": "' + SECRET + '"}')
place(root, 'broken.json', '{"name": "' + SECRET + '", oops')
big = '[' + ' ' * (5 * 1024 * 1024) + ']'
place(root, 'big.json', big)
secret_file = place(outside, 'outside.jsonl', '{"' + SECRET + '": 1}')
os.symlink(secret_file, os.path.join(root, 'link.jsonl'))
os.symlink(outside, os.path.join(root, 'dirlink'))
os.mkdir(os.path.join(root, 'folder.json'))


def path_refused(path, *expected):
    body = post(LABELS, rules_path=path)
    eq(CheckmkServiceLabelRule.objects.count(), 0, f'{path} wrote rules')
    if SECRET in body.replace(path, ''):
        fail(f'{path}: the page shows the file content')
    if 'Import finished' in body:
        fail(f'{path} was imported')
    for part in expected:
        if part not in body:
            fail(f'{path}: {part!r} missing in {shown(body)}')


FOLDER_ONLY = 'must lead to a file in the Files folder'
path_refused(secret_file, FOLDER_ONLY)
path_refused('/etc/passwd', FOLDER_ONLY)
path_refused('../' + os.path.basename(outside) + '/outside.jsonl', FOLDER_ONLY)
path_refused('sub/../../etc/passwd', FOLDER_ONLY)
path_refused('rules.jsonl\0.txt', FOLDER_ONLY)
path_refused('notes.txt', 'Only files ending in')
path_refused('link.jsonl', 'symbolic link')
path_refused('dirlink/outside.jsonl', 'symbolic link')
path_refused('folder.json', 'not a regular file')
path_refused('missing.json', "can&#39;t be read")
path_refused('big.json', 'larger than 5 MB')
path_refused('content.json', 'unknown field(s)')
path_refused('broken.json', 'Not valid JSON')
path_refused('other.jsonl', 'cmk_filter')
path_refused('CheckmkFilterRule_202601010000.syncer_json', 'cmk_filter')
path_refused('cmk_filter.json', 'cmk_filter')

# An older export: no rule_type line, and named after the view by then
INVENTORIZE = next(v.url + '/' for v in admin._views
                   if getattr(v, 'model', None) is CheckmkInventorizeAttributes)
OLD_EXPORT = json.dumps({'_id': {'$oid': 'a' * 24}, 'attribute_source': 'cmk_labels',
                         'attribute_names': 'role'})
place(root, 'Inventorize_from_Checkmk_Settings_202601010000.syncer_json', OLD_EXPORT)
post(INVENTORIZE, rules_path='Inventorize_from_Checkmk_Settings_202601010000.syncer_json')
eq(CheckmkInventorizeAttributes.objects.count(), 1, 'old export by its old name')
CheckmkInventorizeAttributes.objects.delete()
post(INVENTORIZE, rules_text=OLD_EXPORT)
eq(CheckmkInventorizeAttributes.objects.count(), 1, 'old export pasted')
CheckmkInventorizeAttributes.objects.delete()

# A lookup table from the command line has no rule_type line either
place(root, 'LookupTable_202601010000.syncer_json',
      json.dumps({'name': 'sites', 'entries': 'location;datacenter\nsite-a;DC1'}))
TABLES = next(v.url + '/' for v in admin._views if getattr(v, 'model', None) is LookupTable)
post(TABLES, rules_path='LookupTable_202601010000.syncer_json')
eq([x.name for x in LookupTable.objects], ['sites'], 'lookup table file')
LookupTable.objects.delete()
path_refused('LookupTable_202601010000.syncer_json', 'lookup_tables')

body = post(LABELS, rules_path='rules.jsonl')
eq([x.name for x in CheckmkServiceLabelRule.objects], ['good'], 'relative path')
post(LABELS, rules_path=os.path.join(root, 'sub',
                                     'CheckmkServiceLabelRule_202601010000.syncer_json'))
eq(sorted(x.name for x in CheckmkServiceLabelRule.objects), ['from_sub', 'good'], 'absolute path')
CheckmkServiceLabelRule.objects.delete()
body = post(LABELS, rules_path='rules.jsonl', rules_text=GOOD)
if 'not both' not in body:
    fail('text and path together')
eq(CheckmkServiceLabelRule.objects.count(), 0, 'text and path together')

# ---------- Who ----------
if post(LABELS, 'check', rules_text=GOOD).find('name="rules_path"') < 0:
    fail('no path field for an admin')

def member(email, **attributes):
    account = User(email=email, name=email, **attributes)
    account.set_password('smoke-password')
    account.save()
    the_client = app.test_client()
    login(the_client, email, 'smoke-password')
    return the_client


editor = member('editor@example.com', roles=['checkmk'])
body = editor.get(LABELS + 'rule_import/').get_data(as_text=True)
if 'name="rules_path"' in body:
    fail('path field without the Files right')
post(LABELS, the_client=editor, rules_text=GOOD)
eq(CheckmkServiceLabelRule.objects.count(), 1, 'the right of the view is enough to paste')
CheckmkServiceLabelRule.objects.delete()
body = post(LABELS, the_client=editor, rules_path='rules.jsonl')
if 'needs the permission' not in body:
    fail('path without the Files right')
eq(CheckmkServiceLabelRule.objects.count(), 0, 'path without the Files right')

other = member('other@example.com', roles=['host'])
response = other.get(LABELS + 'rule_import/')
eq(response.status_code, 302, 'no right for this rule type')
response = other.post(LABELS + 'rule_import/', data={'rules_text': GOOD, 'action': 'import'})
eq(response.status_code in (302, 400), True, 'POST without the right')
eq(CheckmkServiceLabelRule.objects.count(), 0, 'POST without the right')

reader = member('reader@example.com', roles=['checkmk'], readonly=True)
if LABELS + 'rule_import/' in reader.get(LABELS).get_data(as_text=True):
    fail('import offered to a read-only user')
eq(reader.get(LABELS + 'rule_import/').status_code, 403, 'read-only GET')
response = reader.post(LABELS + 'rule_import/', data={
    'rules_text': GOOD, 'action': 'import',
    'csrf_token': form_token(LABELS)})
eq(response.status_code in (302, 400, 403), True, 'read-only POST')
eq(CheckmkServiceLabelRule.objects.count(), 0, 'read-only POST')

# No token, no import
response = client.post(LABELS + 'rule_import/', data={'rules_text': GOOD, 'action': 'import'})
eq(response.status_code, 400, 'POST without CSRF token')
eq(CheckmkServiceLabelRule.objects.count(), 0, 'POST without CSRF token')

# The command line still reads what the page exports
from application.plugins.rules.rule_import_export import import_rules
CheckmkServiceLabelRule(name='cli', enabled=True).save()
exported = check(LABELS + 'export/syncer_rules/', 200).get_data(as_text=True)
CheckmkServiceLabelRule.objects.delete()
import_rules(place(outside, 'export.syncer_json', exported))
eq([x.name for x in CheckmkServiceLabelRule.objects], ['cli'], 'CLI import of the export')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class RuleFileImportTests(unittest.TestCase):

    def _run(self, part):
        result = run_against_app(PREAMBLE + part, 'False')
        self.assertEqual(result.returncode, 0, result.stderr[-3000:] + result.stdout[-1000:])

    def test_every_rule_type_takes_its_export_back(self):
        self._run(ROUND_TRIP)

    def test_behaviour_path_and_permissions(self):
        self._run(BEHAVIOUR)


if __name__ == '__main__':
    unittest.main()
