"""
Go Live with Shadow Data: the account action that turns the shadow data
of a shadow source into the live labels of its hosts.

Runs against the real app like ``tests/test_web_requests_smoke.py``, see
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


GO_LIVE = LOGIN + '''
from application.models.account import Account, CMDB_SOURCE_ACCOUNT_ID
from application.models.host import Host

old = Account(name='old', type='csv', address='', enabled=True)
old.save()
new = Account(name='new', type='csv', address='', enabled=True, shadow_mode=True)
new.save()
empty = Account(name='empty', type='csv', address='', enabled=True, shadow_mode=True)
empty.save()


def host(name, owner_id, owner_name, shadow):
    obj = Host(hostname=name, labels={'site': 'Berlin'},
               source_account_id=owner_id, source_account_name=owner_name)
    if shadow:
        obj.shadow_labels = {'site': 'Frankfurt', 'rack': 'R1'}
        obj.shadow_account_name = 'new'
    obj.save()


host('srv01', str(old.id), 'old', True)
host('srv02', str(old.id), 'old', False)
host('srv03', CMDB_SOURCE_ACCOUNT_ID, 'cmdb', True)

check('/admin/account/', 200)
check('/admin/account/action/', 302, method='post', data={
    'action': 'take_over_shadow', 'rowid': [str(new.id), str(empty.id)],
    'url': '/admin/account/', 'csrf_token': csrf('/admin/account/'),
})

live = Host.objects.get(hostname='srv01')
eq(live.labels, {'site': 'Frankfurt', 'rack': 'R1'}, 'labels of the taken host')
eq(live.source_account_name, 'new', 'owner of the taken host')
eq(live.shadow_labels, {}, 'shadow labels of the taken host')
eq(live.shadow_account_name, None, 'shadow account of the taken host')

untouched = Host.objects.get(hostname='srv02')
eq(untouched.labels, {'site': 'Berlin'}, 'labels of a host without shadow data')
eq(untouched.source_account_name, 'old', 'owner of a host without shadow data')

locked = Host.objects.get(hostname='srv03')
eq(locked.labels, {'site': 'Berlin'}, 'labels of a refused host')
eq(locked.shadow_account_name, 'new', 'shadow data of a refused host')

new.reload()
eq((new.shadow_mode, new.is_master), (False, True), 'flags of the account')
empty.reload()
eq((empty.shadow_mode, empty.is_master), (True, False), 'flags of an account without data')
print('GO_LIVE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestShadowGoLive(unittest.TestCase):
    """The account action Go Live with Shadow Data."""

    def test_shadow_data_goes_live(self):
        """Taken hosts get the labels, refused ones and other accounts stay."""
        result = run_against_app(GO_LIVE, 'False')
        self.assertIn('GO_LIVE_OK', result.stdout,
                      f"\n{result.stdout[-800:]}\n{result.stderr[-3000:]}")


if __name__ == '__main__':
    unittest.main()
