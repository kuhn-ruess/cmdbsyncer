"""
Shared account multi-select form field.

Several admin views let an operator scope something to a set of accounts,
stored as a plain list of account names (Project export scope, API user
account allowlist, …). They all want the same widget and the same choice
source, so it lives here once instead of being copied per view.
"""
from flask_admin.form.widgets import Select2Widget
from wtforms import SelectMultipleField

from application.models.account import Account


def account_choices():
    """All enabled accounts as (name, label) pairs, ordered by name."""
    return [(a.name, f"{a.name} ({a.type})")
            for a in Account.objects(enabled=True).order_by('name')]


class AccountsMultiSelectField(SelectMultipleField):
    """Multi-select of accounts, stored as a list of account names."""
    # Select2 chips instead of the native multi-select listbox: the native
    # widget needs Ctrl/Cmd-click and barely highlights the selection on
    # the dark themes — with chips the picked accounts are always visible.
    widget = Select2Widget(multiple=True)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('choices', account_choices)
        # Tolerate a saved name whose account was since disabled/removed.
        kwargs.setdefault('validate_choice', False)
        super().__init__(*args, **kwargs)
