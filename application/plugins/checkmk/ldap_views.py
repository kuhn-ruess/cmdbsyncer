"""
Checkmk LDAP Connection View
"""
from flask_admin.form import rules
from flask_login import current_user
from wtforms import SelectField

from application.docu_links import docu_links
from application.models.account import Account
from application.views.default import DefaultModelView
from application.views._form_sections import modern_form, section


def _ldap_accounts():
    """Every enabled LDAP account"""
    return [(a.name, a.name) for a in
            Account.objects(enabled=True, type='ldap').order_by('name')]


class CheckmkLdapConnectionView(DefaultModelView):
    """
    Checkmk LDAP Connections
    """
    column_list = ('connection_id', 'description', 'ldap_account',
                   'user_base_dn', 'deactivated', 'remove_if_found')

    column_editable_list = ('deactivated', 'remove_if_found')

    column_labels = {
        'connection_id': "Connection ID",
        'ldap_account': "LDAP Account",
        'user_base_dn': "User Base DN",
        'user_filter_group': "Filter Group",
        'user_id_attribute': "User ID Attribute",
        'lower_user_ids': "Lower Case User IDs",
        'group_base_dn': "Group Base DN",
        'sync_alias': "Alias Attribute",
        'sync_email': "Email Attribute",
        'sync_pager': "Pager Attribute",
        'sync_contact_groups': "Sync Contact Groups",
        'role_mappings': "Groups to Roles",
        'sync_interval': "Sync Interval (Minutes)",
    }

    form_overrides = {
        'ldap_account': SelectField,
    }

    form_args = {
        'ldap_account': {
            'choices': _ldap_accounts,
            # A saved account that was since disabled or removed must not
            # block editing the rest of the connection.
            'validate_choice': False,
            'description': "Server, port, SSL (ldaps://), bind DN and password "
                           "are taken from this LDAP Account.",
        },
        'connection_id': {
            'description': "ID of the connection in Checkmk, e.g. ldap_ad.",
        },
        'bind_secret': {
            'description': "Optional: name of a global Secret Store entry. "
                           "Checkmk then binds with it out of its password store "
                           "(export the passwords first) instead of the account password.",
        },
        'failover_servers': {
            'description': "Servers tried when the account's server is not reachable.",
        },
        'connection_suffix': {
            'description': "Appended to the user IDs (user@suffix) when more than "
                           "one connection may have the same user names.",
        },
        'user_filter_group': {
            'description': "DN of a group, only its members may log in.",
        },
        'user_id_attribute': {
            'description': "Empty uses Checkmk's default (sAMAccountName / uid).",
        },
        'member_attribute': {
            'description': "Empty uses Checkmk's default (member / uniqueMember).",
        },
        'sync_email': {
            'description': "LDAP attribute for the mail address, e.g. mail.",
        },
        'role_mappings': {
            'description': "Role is the Checkmk role ID (admin, user, guest, ...). "
                           "Each group DN must be below the Group Base DN.",
        },
        'handle_nested_groups': {
            'description': "Also members of nested groups get the contact groups and roles.",
        },
        'deactivated': {
            'description': "Keep the connection in Checkmk, but deactivated.",
        },
        'remove_if_found': {
            'description': "Delete the connection from Checkmk.",
        },
    }

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_ldap_connections"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Connection',
                    'Which directory Checkmk asks, and how.',
                    [rules.Field('connection_id'),
                     rules.Field('description'),
                     rules.Field('comment'),
                     rules.Field('ldap_account'),
                     rules.Field('directory_type'),
                     rules.Field('failover_servers'),
                     rules.Field('bind_secret'),
                     rules.Field('connection_suffix')]),
            section('2', 'cond', 'Users & Groups',
                    'Where the users and groups are found.',
                    [rules.Field('user_base_dn'),
                     rules.Field('user_search_filter'),
                     rules.Field('user_filter_group'),
                     rules.Field('user_id_attribute'),
                     rules.Field('lower_user_ids'),
                     rules.Field('create_users'),
                     rules.Field('group_base_dn'),
                     rules.Field('group_search_filter'),
                     rules.Field('member_attribute')]),
            section('3', 'out', 'Synchronization',
                    'What Checkmk takes over from the directory.',
                    [rules.Field('sync_alias'),
                     rules.Field('sync_email'),
                     rules.Field('sync_pager'),
                     rules.Field('sync_contact_groups'),
                     rules.Field('role_mappings'),
                     rules.Field('handle_nested_groups'),
                     rules.Field('sync_interval')]),
            section('4', 'aux', 'Lifecycle',
                    'State of the connection in Checkmk.',
                    [rules.Field('deactivated'),
                     rules.Field('remove_if_found')]),
        ),
    ]

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')
