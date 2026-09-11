"""
Checkmk User Models

The Checkmk users the Syncer manages, and the rules generating them out
of host attributes. Kept next to, not inside, ``models.py`` — that module
carries the export rules and is at its size budget.
"""
# Mongoengine Document classes are data carriers; they don't need
# additional public methods to satisfy pylint.
# pylint: disable=too-few-public-methods
from application import db


#   .-- Checkmk User Management
class CheckmkUserMngmt(db.Document):
    """
    Manage Checkmk Users
    """
    documentation = db.StringField()
    user_id = db.StringField(required=True)
    full_name = db.StringField(required=True)
    email = db.StringField()
    pager_address = db.StringField()

    roles = db.ListField(field=db.StringField(), default=['admin'])
    contact_groups = db.ListField(field=db.StringField(), default=['all'])

    password = db.StringField(required=True)
    overwrite_password = db.BooleanField()
    force_password_change = db.BooleanField()
    disable_login = db.BooleanField()
    remove_if_found = db.BooleanField()

    disabled = db.BooleanField(default=False)

    # Name of the CheckmkUserGenerationRule which created this entry.
    # Empty means the user was created by hand — the generation never
    # overwrites such an entry.
    generated_by_rule = db.StringField()

    meta = {
        'strict': False
    }

#.
#   .-- Checkmk User Generation

user_foreach_types = [
 ('label', "Foreach Attribute Name"),
 ('value', "Foreach Attribute Value"),
 ('list', "Foreach Value in List for given Attribute"),
]


class CmkUserGenerationOutcome(db.EmbeddedDocument):
    """
    One Checkmk User per LDAP Group your Hosts carry.

    The Group Name comes from a Host Attribute. The Account is only the
    Connection to the Directory - where the Groups are searched and how
    they are read is part of this Rule. Every Attribute the Group Object
    carries is then available as a Jinja Variable, so Mail, Pager and the
    Names can be built from it. Every Field below says what it does.
    """
    # Field order is form order: pick the groups, say where they are read,
    # then build the user out of what they carry.
    foreach_type = db.StringField(choices=user_foreach_types)
    foreach = db.StringField(required=False)
    rewrite_group_name = db.StringField()

    ldap_account = db.StringField()
    ldap_base_dn = db.StringField()
    ldap_group_filter = db.StringField()
    ldap_name_attribute = db.StringField(default='cn')
    ldap_attributes = db.StringField()

    rewrite_user_id = db.StringField(default='{{name}}')
    rewrite_full_name = db.StringField(default='{{name}}')
    rewrite_email = db.StringField(default='{{mail}}')
    rewrite_pager_address = db.StringField()

    roles = db.ListField(field=db.StringField(), default=['user'])
    contact_groups = db.ListField(field=db.StringField(), default=['all'])
    disable_login = db.BooleanField(default=True)

    meta = {
        'strict': False,
    }


class CheckmkUserGenerationRule(db.Document):
    """
    Create Checkmk Users out of Host Attributes
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    outcome = db.EmbeddedDocumentField(document_type="CmkUserGenerationOutcome")
    render_checkmk_user_generation_outcome = db.StringField()
    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }

#.
