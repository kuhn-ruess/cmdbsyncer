"""
Smoke test: Data Quality, Templates by host list assigns a template to the
pasted hosts or removes it from them, after a preview that changes nothing.
"""
import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app

SNIPPET = '''
from datetime import datetime
from application.models.host import Host

def make(name, object_type='server', templates=(), archived=False):
    host = Host(hostname=name, object_type=object_type,
                is_object=object_type == 'template')
    host.cmdb_templates = list(templates)
    if archived:
        host.deleted_at = datetime.utcnow()
    host.save()
    return host

tpl_a = make('tpl_a', 'template')
tpl_b = make('tpl_b', 'template')
make('srv01', templates=[tpl_a, tpl_b])
make('srv02', templates=[tpl_b])
make('srv03')
make('srv04', templates=[tpl_b], archived=True)

def names(hostname):
    return [t.hostname for t in Host.objects.get(hostname=hostname).cmdb_templates]

client.post('/login', data={'login_email': 'smoke@example.com',
                            'password': 'smoke-password', 'otp': '',
                            'login_submit': 'Login', 'csrf_token': csrf('/login')})
if 'Templates by host list' not in check('/admin/data_quality/', 200).get_data(as_text=True):
    fail('link on the dashboard missing')
url = '/admin/data_quality/host_templates'
pasted = 'srv01, srv02\\nsrv03 srv04 srv99'

# Remove: the preview lists the hosts and changes nothing.
form = {'hostnames': pasted, 'template_id': str(tpl_b.id), 'mode': 'remove'}
page = check(url, 200, method='post', data={**form, 'csrf_token': csrf(url)}
             ).get_data(as_text=True)
if 'Remove template from 2 host(s)' not in page:
    fail('remove preview wrong')
eq(names('srv01'), ['tpl_a', 'tpl_b'], 'srv01 after preview')
check(url, 302, method='post', data={**form, 'apply': '1', 'csrf_token': csrf(url)})
eq(names('srv01'), ['tpl_a'], 'srv01 after remove')
eq(names('srv02'), [], 'srv02 after remove')
eq(names('srv04'), ['tpl_b'], 'archived srv04 after remove')

# Assign: only hosts without it get the template.
form = {'hostnames': pasted, 'template_id': str(tpl_a.id), 'mode': 'assign'}
page = check(url, 200, method='post', data={**form, 'csrf_token': csrf(url)}
             ).get_data(as_text=True)
if 'Assign template to 2 host(s)' not in page:
    fail('assign preview wrong')
check(url, 302, method='post', data={**form, 'apply': '1', 'csrf_token': csrf(url)})
eq(names('srv01'), ['tpl_a'], 'srv01 after assign')
eq(names('srv02'), ['tpl_a'], 'srv02 after assign')
eq(names('srv03'), ['tpl_a'], 'srv03 after assign')
eq(names('srv04'), ['tpl_b'], 'archived srv04 after assign')
print('HOST_TEMPLATES_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class DataQualityHostTemplatesTests(unittest.TestCase):
    """Runs the snippet against the booted app."""

    def test_assign_and_remove_by_host_list(self):
        """Paste hosts, preview, then assign and remove a template."""
        result = run_against_app(SNIPPET, True)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        self.assertIn('HOST_TEMPLATES_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
