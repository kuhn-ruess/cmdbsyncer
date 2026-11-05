"""
Every column a list offers for inline edit has to save.

Inline edit posts a form holding that one column, so a view whose
``on_model_change`` reads any other field of the form fails. Runs through
all registered views, so a new view is covered without touching this test.

See ``tests/web_smoke_helpers.py`` for why this needs a subprocess.
"""

import unittest

from tests.web_smoke_helpers import HAVE_MONGOMOCK, SKIP_REASON, run_against_app


SNIPPET = '''
from mongoengine import fields

from application import admin as admin_extension

client.post('/login', data={
    'login_email': 'smoke@example.com', 'password': 'smoke-password',
    'otp': '', 'login_submit': 'Login', 'csrf_token': csrf('/login'),
})
token = csrf('/admin/user/new/')


def sample(field, number):
    """A value for a required or naming field of a probe document."""
    if field.choices:
        choice = list(field.choices)[0]
        return choice[0] if isinstance(choice, (list, tuple)) else choice
    if isinstance(field, fields.EmailField):
        return f'probe{number}@example.com'
    if isinstance(field, fields.IntField):
        return 1
    if isinstance(field, fields.StringField):
        return f'probe{number}'
    return None


def probe_document(view, number):
    """A saved document of the view's model, unvalidated: only one column
    is about to be edited."""
    document = view.model()
    for name, field in document._fields.items():
        if field.required or name in ('name', 'email'):
            value = sample(field, number)
            if value is not None:
                setattr(document, name, value)
    document.save(validate=False)
    return document


def new_value(field, current):
    """What the frontend would send for this column."""
    if isinstance(field, fields.BooleanField):
        return '' if current else '1'
    return '7' if isinstance(field, fields.IntField) else 'probe-value'


tested = 0
for number, view in enumerate(admin_extension._views):
    columns = getattr(view, 'column_editable_list', None)
    if not columns:
        continue
    document = probe_document(view, number)
    for column in map(str, columns):
        field = view.model._fields[column]
        # A flash of the view before would end up in this error message.
        with client.session_transaction() as session:
            session.pop('_flashes', None)
        response = client.post(view.url.rstrip('/') + '/ajax/update/', data={
            'list_form_pk': str(document.id),
            column: new_value(field, getattr(document, column, None)),
            'csrf_token': token,
        })
        body = response.get_data(as_text=True)
        # The probe document leaves references empty, the model refusing
        # them is no finding.
        if response.status_code != 200 and 'Field is required' not in body:
            fail(f'{type(view).__name__}.{column}: '
                 f'{response.status_code} {body[:200]}')
        tested += 1

if tested < 20:
    fail(f'only {tested} inline columns found')
print('INLINE_EDIT_OK')
'''


@unittest.skipUnless(HAVE_MONGOMOCK, SKIP_REASON)
class InlineEditTests(unittest.TestCase):
    """Runs SNIPPET against the booted app."""

    def test_every_inline_column_saves(self):
        """No view may depend on form fields inline edit doesn't send."""
        result = run_against_app(SNIPPET, False)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        self.assertIn('INLINE_EDIT_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
