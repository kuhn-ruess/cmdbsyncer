"""
Project
"""
# pylint: disable=too-few-public-methods
from application import db


class Project(db.Document):
    """
    Groups syncer objects (currently Checkmk Setup Rules, DCD rules and
    hosts — more may follow) and limits which accounts they are exported
    to. ``limit_by_accounts`` restricts the project's members to the
    listed accounts; an empty list means no restriction.
    ``deny_by_accounts`` excludes accounts and wins over the allow list.

    The account-scope decision itself lives with the consumers (see
    ``application.plugins.checkmk.helpers.project_allows_account``) —
    this document only carries the data.
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    # Names of the accounts this project's members may be exported to.
    # Empty = no restriction (all accounts). Stored by name to survive
    # JSON im-/export between separate syncer instances.
    limit_by_accounts = db.ListField(field=db.StringField())

    # Names of the accounts this project's members are never exported to.
    # The deny list wins over ``limit_by_accounts``.
    deny_by_accounts = db.ListField(field=db.StringField())

    meta = {
        'strict': False,
    }
