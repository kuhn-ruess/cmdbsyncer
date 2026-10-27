"""
Checkmk LDAP Connection Models

The LDAP connections Checkmk authenticates its users against. Kept next
to, not inside, ``models.py`` — that module is at its size budget.
"""
# Mongoengine Document classes are data carriers; they don't need
# additional public methods to satisfy pylint.
# pylint: disable=too-few-public-methods
from application import db


directory_types = [
    ('active_directory_manual', "Active Directory"),
    ('open_ldap', "OpenLDAP"),
    ('389_directory_server', "389 Directory Server"),
]

create_users_types = [
    ('on_login', "On first login"),
    ('on_sync', "During sync"),
]


class CheckmkLdapRoleMapping(db.EmbeddedDocument):
    """
    Members of an LDAP Group get a Checkmk Role
    """
    role = db.StringField(required=True)
    group_dn = db.StringField(required=True)

    meta = {
        'strict': False
    }


class CheckmkLdapConnection(db.Document):
    """
    LDAP Connection for the Checkmk Login
    """
    connection_id = db.StringField(required=True, unique=True)
    description = db.StringField()
    comment = db.StringField()

    # Server, bind DN and password come from this Syncer LDAP Account.
    ldap_account = db.StringField(required=True)
    directory_type = db.StringField(choices=directory_types,
                                    default='active_directory_manual')
    failover_servers = db.ListField(field=db.StringField())
    # Name of a global Secret Store entry. Checkmk then binds with that
    # entry from its own password store instead of the account password.
    bind_secret = db.StringField()
    connection_suffix = db.StringField()

    user_base_dn = db.StringField(required=True)
    user_search_filter = db.StringField()
    user_filter_group = db.StringField()
    user_id_attribute = db.StringField()
    lower_user_ids = db.BooleanField(default=False)
    create_users = db.StringField(choices=create_users_types, default='on_login')

    group_base_dn = db.StringField()
    group_search_filter = db.StringField()
    member_attribute = db.StringField()

    sync_alias = db.StringField()
    sync_email = db.StringField()
    sync_pager = db.StringField()
    sync_contact_groups = db.BooleanField(default=False)
    role_mappings = db.ListField(
        field=db.EmbeddedDocumentField(document_type="CheckmkLdapRoleMapping"))
    handle_nested_groups = db.BooleanField(default=False)

    sync_interval = db.IntField(default=5, min_value=1)

    deactivated = db.BooleanField(default=False)
    remove_if_found = db.BooleanField(default=False)

    meta = {
        'strict': False
    }
