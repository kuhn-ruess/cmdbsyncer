"""
Shared Flask-Admin form fields.

``AccountSelectField`` renders as a dropdown of all enabled Syncer
Accounts — the source of truth for outbound credentials. Admin views
that hold a reference-by-name to an Account (notification webhook
signing secret, audit-log SIEM token, backup destination credentials,
…) plug it in through ``form_overrides`` so the form has a pickable
list instead of a free-text input.

The choices are resolved lazily per request, so newly created Accounts
show up without restarting the app.
"""
from wtforms import SelectField

from application.models.account import Account


def _account_choices():
    names = [a.name for a in Account.objects(enabled=True).order_by('name')]
    return [('', '— none —'), *((n, n) for n in names)]


class AccountSelectField(SelectField):
    """SelectField populated from the Account collection at render time."""
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('choices', _account_choices)
        # Accept a previously-saved name that points to an Account which
        # has since been disabled or deleted, so editing a row without
        # touching that field still works.
        kwargs.setdefault('validate_choice', False)
        super().__init__(*args, **kwargs)
