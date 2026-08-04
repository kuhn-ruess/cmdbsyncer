"""
Project
"""
# pylint: disable=too-few-public-methods
from application import db


class Project(db.Document):
    """
    Groups syncer objects (currently Checkmk Setup Rules, DCD rules and
    hosts — more may follow) and limits which accounts they are exported
    to. Hosts and rules are steered separately: ``limit_by_accounts`` /
    ``deny_by_accounts`` govern the hosts, while ``rule_limit_by_accounts``
    / ``rule_deny_by_accounts`` govern the Setup/DCD rules. Each rule list
    falls back to its host counterpart when left empty, so a project that
    only fills the host lists keeps steering its rules the same way.

    Objects assigned to a project ignore an account's Checkmk folder scope
    (``limit_by_folders``): a project routes its members purely by these
    account lists, and the folder scope only ever gates project-less
    objects.

    The account-scope decision itself lives with the consumers (see
    ``application.plugins.checkmk.helpers.project_allows_account``) —
    this document only carries the data.
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()

    # Names of the accounts this project's HOSTS may be exported to.
    # Empty = no restriction (all accounts). Stored by name to survive
    # JSON im-/export between separate syncer instances.
    limit_by_accounts = db.ListField(field=db.StringField())

    # Names of the accounts this project's HOSTS are never exported to.
    # The deny list wins over ``limit_by_accounts``.
    deny_by_accounts = db.ListField(field=db.StringField())

    # Same as above, but for the project's Setup/DCD RULES — so rules can
    # be promoted (e.g. test first, prod later) independently of the
    # hosts. Empty falls back to the matching host list above.
    rule_limit_by_accounts = db.ListField(field=db.StringField())
    rule_deny_by_accounts = db.ListField(field=db.StringField())

    meta = {
        'strict': False,
    }
