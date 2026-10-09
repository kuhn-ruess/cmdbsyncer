"""
A password typed into the account form reaches the account encrypted,
also when the form is saved some other way than the view's own.

The approval workflow of the enterprise add-on replaces the view's
create_model / update_model: it fills a new account or a copy of the
existing one from the form, stores that document and writes it back as
it is once the change is approved. on_model_change never runs on that
way. When the password was only encrypted there, the typed password
stayed in the plain text field of the stored copy, and on approval the
account kept its old encrypted password, so the new one never took
effect.

The interception below does what the add-on does, so the test runs the
real form through the same path without needing the add-on.

Runs against the real app like ``tests/test_web_requests_smoke.py``, see
``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.test_web_requests_smoke import LOGIN
from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = LOGIN + r'''
from bson import ObjectId
from application.models.account import Account
from application.views.account import AccountModelView

view = next(v for v in app.extensions['admin'][0]._views
            if isinstance(v, AccountModelView))
QUEUE = []


def create_model(form):
    """Fill a new account from the form and keep it for later."""
    temp = Account()
    form.populate_obj(temp)
    QUEUE.append(('create', None, temp.to_mongo().to_dict()))
    return temp


def update_model(form, model):
    """Fill a copy of the account from the form and keep it for later."""
    clone = Account._from_son(model.to_mongo().to_dict())
    form.populate_obj(clone)
    QUEUE.append(('update', model.pk, clone.to_mongo().to_dict()))
    return True


def approve():
    """Write the kept documents back as they are."""
    collection = Account._get_collection()
    while QUEUE:
        operation, pk, data = QUEUE.pop(0)
        data.pop('_id', None)
        if operation == 'create':
            collection.insert_one(data)
        else:
            collection.replace_one({'_id': ObjectId(str(pk))}, data)


view.create_model = create_model
view.update_model = update_model

FIRST = 'Grüße§´ß€\\'
SECOND = 'ä ß § € ´ \\ "x"'

form = '/admin/account/new/?type=custom'
check(form, 302, method='post', data={
    'csrf_token': csrf(form),
    'name': 'deferred-account',
    'address': 'https://example.org',
    'enabled': 'y',
    'password': FIRST,
})
eq(len(QUEUE), 1, 'create kept for later')
eq(Account.objects(name='deferred-account').count(), 0,
   'account before approval')
approve()
account = Account.objects.get(name='deferred-account')
eq(account.password, '', 'plain text password after create')
eq(account.get_password(), FIRST, 'password after create')

edit = f'/admin/account/edit/?id={account.pk}'
check(edit, 302, method='post', data={
    'csrf_token': csrf(edit),
    'name': 'deferred-account',
    'address': 'https://example.org',
    'enabled': 'y',
    'password': SECOND,
})
eq(Account.objects.get(name='deferred-account').get_password(), FIRST,
   'password before approval')
approve()
account = Account.objects.get(name='deferred-account')
eq(account.password, '', 'plain text password after edit')
eq(account.get_password(), SECOND, 'password after edit')

check(edit, 302, method='post', data={
    'csrf_token': csrf(edit),
    'name': 'deferred-account',
    'address': 'https://example.org/changed',
    'enabled': 'y',
    'password': '',
})
approve()
account = Account.objects.get(name='deferred-account')
eq(account.address, 'https://example.org/changed', 'address after edit')
eq(account.get_password(), SECOND, 'password kept by an empty field')
print('DEFERRED_SAVE_OK')
'''

DIRECT = LOGIN + r'''
from application.models.account import Account

PASSWORD = 'Grüße§´ß€\\'
form = '/admin/account/new/?type=custom'
check(form, 302, method='post', data={
    'csrf_token': csrf(form),
    'name': 'direct-account',
    'address': 'https://example.org',
    'enabled': 'y',
    'password': PASSWORD,
})
account = Account.objects.get(name='direct-account')
eq(account.password, '', 'plain text password after create')
eq(account.get_password(), PASSWORD, 'password after create')

edit = f'/admin/account/edit/?id={account.pk}'
check(edit, 302, method='post', data={
    'csrf_token': csrf(edit),
    'name': 'direct-account',
    'address': 'https://example.org/changed',
    'enabled': 'y',
    'password': '',
})
account = Account.objects.get(name='direct-account')
eq(account.address, 'https://example.org/changed', 'address after edit')
eq(account.get_password(), PASSWORD, 'password kept by an empty field')

legacy = Account(name='legacy-account', type='custom', password='old plain')
legacy.save()
edit = f'/admin/account/edit/?id={legacy.pk}'
body = check(edit, 200).get_data(as_text=True)
if 'old plain' not in body:
    fail('legacy plain text password not shown in the form')
check(edit, 302, method='post', data={
    'csrf_token': csrf(edit),
    'name': 'legacy-account',
    'enabled': 'y',
    'password': 'old plain',
})
legacy = Account.objects.get(name='legacy-account')
eq(legacy.password, '', 'legacy plain text password after edit')
eq(legacy.get_password(), 'old plain', 'legacy password after edit')
print('DIRECT_SAVE_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class TestAccountPasswordDeferredSave(unittest.TestCase):
    """The account form encrypts the password whichever way it is saved."""

    def _run(self, snippet, marker):
        result = run_against_app(snippet, 'False')
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertIn(marker, result.stdout)

    def test_password_survives_a_deferred_save(self):
        """Create and edit through a held back save keep the new password."""
        self._run(SNIPPET, 'DEFERRED_SAVE_OK')

    def test_password_on_the_normal_save(self):
        """The normal save encrypts, keeps and migrates as before."""
        self._run(DIRECT, 'DIRECT_SAVE_OK')


if __name__ == '__main__':
    unittest.main()
