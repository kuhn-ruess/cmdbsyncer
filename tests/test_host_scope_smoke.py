"""
A user limited to an account or template doesn't reach foreign hosts through
any bulk action or page, however the id gets there; others lose nothing.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from application import limiter
from application.models.field_approval import FieldApproval
from application.models.host import Host
from application.models.project import Project

limiter.enabled = False
app.config['APPROVAL_REQUIRED_LABELS'] = ['critical']

ROLES = ['host', 'objects', 'approval']


def make_user(email, **fields):
    new = User(email=email, name=email, roles=ROLES, **fields)
    new.set_password('smoke-password')
    new.save()


make_user('limited@example.com', restrict_to_accounts=['own'])
make_user('open@example.com')


def login(email):
    global client, TOKEN
    client = app.test_client()
    response = client.post('/login', data={
        'login_email': email, 'password': 'smoke-password',
        'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
    })
    eq(response.status_code, 302, f'login of {email}')
    TOKEN = csrf('/set-theme')


def new_host(name, account='other', **fields):
    host = Host(hostname=name, source_account_id=account, source_account_name=account,
                labels={'site': 'ber'}, **fields)
    host.save()
    return host


Project(name='proj').save()
template = Host(hostname='tpl', object_type='template', is_object=True,
                source_account_name='cmdb', source_account_id='cmdb')
template.save()
foreign = new_host('foreign-host-name', shadow_account_name='sh', shadow_labels={'s': 'h'})
foreign_object = new_host('foreign-object-name', is_object=True, object_type='auto')
own = new_host('own-host-name', account='own', shadow_account_name='sh',
               shadow_labels={'s': 'h'})
own_object = new_host('own-object-name', account='own', is_object=True, object_type='auto')
own.add_relation(foreign, 'depends_on')
own.save()
foreign.add_relation(own, 'depends_on')
foreign.save()
foreign_approval = FieldApproval(host_id=str(foreign.id), hostname=foreign.hostname,
                                 field_name='critical', new_value='x', status='pending',
                                 requested_by_email='a@example.com')
foreign_approval.save()
own_approval = FieldApproval(host_id=str(own.id), hostname=own.hostname,
                             field_name='critical', new_value='x', status='pending',
                                 requested_by_email='a@example.com')
own_approval.save()

SNAPSHOT = ('source_account_name', 'project', 'labels', 'lifecycle_state', 'is_object',
            'object_type', 'cmdb_templates', 'shadow_account_name')


def state(host):
    current = Host.objects.get(id=host.id).to_mongo().to_dict()
    return {key: current.get(key) for key in SNAPSHOT}


def bulk(view, action, *hosts):
    client.post(f'/admin/{view}/action/', data={
        'action': action, 'rowid': [str(host.id) for host in hosts],
        'url': f'/admin/{view}/', 'csrf_token': TOKEN,
    })


def post(path, **data):
    client.post(path, data={**data, 'csrf_token': TOKEN})


def writes(host, view='host'):
    """Everything that changes a host, aimed at *host*."""
    ids = str(host.id)
    for name in ('lifecycle_decommissioned', 'lifecycle_archived', 'clear_shadow',
                 'redistribute_site_pool'):
        bulk(view, name, host)
    if view == 'Objects':
        bulk(view, 'make_host', host)
        return
    post('/admin/host/process_project_assignment', host_ids=ids, project='proj')
    post('/admin/host/process_set_account', host_ids=ids, account='own')
    post('/admin/host/process_set_account', host_ids=ids, account='cmdb')
    post('/admin/host/bulk_label_process', host_ids=ids, mode='add',
         label_key='new', label_value='value')
    post('/admin/host/process_template_assignment', host_ids=ids,
         template_id=str(template.id))


# --- limited user: nothing happens to foreign hosts
login('limited@example.com')
before = state(foreign), state(foreign_object)
writes(foreign)
writes(foreign_object, 'Objects')
eq((state(foreign), state(foreign_object)), before, 'foreign hosts after every action')

host_id, object_id = foreign.id, foreign_object.id
post('/admin/host/copy_as_new_process', source_id=str(host_id), new_hostname='stolen')
eq(Host.objects(hostname='stolen').first(), None, 'copy of a foreign host')

for url, name in (
        (f'/admin/host/timeline?obj_id={host_id}', 'foreign-host-name'),
        (f'/admin/host/inventory_tree?obj_id={host_id}', 'foreign-host-name'),
        (f'/admin/host/relations_graph?obj_id={host_id}', 'foreign-host-name'),
        (f'/admin/host/relations_graph_data?obj_id={host_id}', 'foreign-host-name'),
        (f'/admin/host/debug?obj_id={host_id}', 'foreign-host-name'),
        ('/admin/host/debug?hostname=foreign-host-name&mode=checkmk_host', 'site'),
        (f'/admin/host/copy_as_new_form?source_id={host_id}', 'foreign-host-name'),
        (f'/admin/host/details/?id={host_id}', 'foreign-host-name'),
        (f'/admin/host/edit/?id={host_id}', 'foreign-host-name'),
        (f'/admin/Objects/timeline?obj_id={object_id}', 'foreign-object-name'),
        (f'/admin/Objects/debug?obj_id={object_id}', 'foreign-object-name'),
        (f'/admin/Objects/details/?id={object_id}', 'foreign-object-name'),
        (f'/admin/Objects/edit/?id={object_id}', 'foreign-object-name'),
        ('/admin/host/csv', 'foreign-host-name'),
        ('/admin/host/', 'foreign-host-name'),
        ('/admin/Objects/', 'foreign-object-name'),
        ('/admin/fieldapproval/', 'foreign-host-name'),
        (f'/admin/fieldapproval/details/?id={foreign_approval.id}', 'foreign-host-name'),
):
    body = client.get(url, follow_redirects=True).get_data(as_text=True)
    if name == 'site':
        if 'foreign-host-name' in body or '>ber<' in body:
            fail(f'{url} shows a foreign host')
    elif name in body:
        fail(f'{url} shows {name}')

# --- the graph of an own host doesn't name foreign neighbours
graph = client.get(f'/admin/host/relations_graph_data?obj_id={own.id}').get_data(as_text=True)
eq('own-host-name' in graph, True, 'the graph shows the own host')
eq('foreign-host-name' in graph, False, 'the graph shows a foreign neighbour')

bulk('fieldapproval', 'approve', foreign_approval)
eq(FieldApproval.objects.get(id=foreign_approval.id).status, 'pending', 'approve foreign')
bulk('fieldapproval', 'reject', foreign_approval)
eq(FieldApproval.objects.get(id=foreign_approval.id).status, 'pending', 'reject foreign')

# --- ... and their own hosts still work
post('/admin/host/bulk_label_process', host_ids=str(own.id), mode='add',
     label_key='new', label_value='value')
eq(Host.objects.get(id=own.id).get_labels().get('new'), 'value', 'labels of an own host')
post('/admin/host/process_project_assignment', host_ids=str(own.id), project='proj')
eq(Host.objects.get(id=own.id).project, 'proj', 'project of an own host')
bulk('host', 'lifecycle_decommissioned', own)
eq(Host.objects.get(id=own.id).lifecycle_state, 'decommissioned', 'lifecycle of an own host')
bulk('host', 'lifecycle_active', own)
bulk('host', 'clear_shadow', own)
eq(Host.objects.get(id=own.id).shadow_account_name, None, 'shadow of an own host')
bulk('Objects', 'make_host', own_object)
eq(Host.objects.get(id=own_object.id).is_object, False, 'convert an own object')
for url in (f'/admin/host/timeline?obj_id={own.id}', f'/admin/host/debug?obj_id={own.id}',
            f'/admin/host/copy_as_new_form?source_id={own.id}'):
    if 'own-host-name' not in client.get(url).get_data(as_text=True):
        fail(f'{url} lost the own host')
bulk('fieldapproval', 'reject', own_approval)
eq(FieldApproval.objects.get(id=own_approval.id).status, 'rejected', 'reject own')

# --- a user without limits still reaches everything
login('open@example.com')
post('/admin/host/bulk_label_process', host_ids=str(foreign.id), mode='add',
     label_key='new', label_value='value')
eq(Host.objects.get(id=foreign.id).get_labels().get('new'), 'value', 'labels by an open user')
post('/admin/host/process_template_assignment', host_ids=str(foreign.id),
     template_id=str(template.id))
eq(len(Host.objects.get(id=foreign.id).cmdb_templates), 1, 'template by an open user')
if 'foreign-object-name' not in client.get(f'/admin/Objects/edit/?id={object_id}'
                                           ).get_data(as_text=True):
    fail('an open user lost the object form')
bulk('fieldapproval', 'reject', foreign_approval)
eq(FieldApproval.objects.get(id=foreign_approval.id).status, 'rejected', 'reject by an open user')

print('HOST_SCOPE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class HostScopeTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_scope(self):
        """Foreign hosts stay out of reach, open users lose nothing."""
        result = run_against_app(SNIPPET, True)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}")
        self.assertIn('HOST_SCOPE_OK', result.stdout)
