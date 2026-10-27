"""
Export the LDAP Connections Checkmk authenticates its Users against
"""
from urllib.parse import urlparse

from application import logger
from application.helpers.get_account import get_account_by_name, AccountNotFoundError
from application.plugins.checkmk.cmk2 import CMK2, CmkException
from application.plugins.checkmk.ldap_models import CheckmkLdapConnection
from application.plugins.checkmk.rule_passwords import password_ident

from syncerapi.v1 import cc as CC


def _checkbox(key=None, value=None):
    """Checkmk's optional settings: enabled with a value, else disabled"""
    if not value:
        return {"state": "disabled"}
    return {"state": "enabled", key: value}


def _server(address):
    """
    Host, port and SSL out of an LDAP Account address like
    ``ldaps://dc.example.com:636``
    """
    if '://' not in address:
        address = f'ldap://{address}'
    parsed = urlparse(address)
    use_ssl = parsed.scheme.lower() == 'ldaps'
    return parsed.hostname, parsed.port or (636 if use_ssl else 389), use_ssl


def _bind_credentials(connection, account):
    """Bind with the Secret Store entry if set, else with the account password"""
    if not account.get('username'):
        return {"state": "disabled"}
    if connection.bind_secret:
        return {
            "state": "enabled",
            "type": "store",
            "bind_dn": account['username'],
            "password_store_id": password_ident(connection.bind_secret),
        }
    return {
        "state": "enabled",
        "type": "explicit",
        "bind_dn": account['username'],
        "explicit_password": account['password'],
    }


def _sync_plugins(connection):
    """User attributes, contact groups and roles Checkmk takes from LDAP"""
    plugins = {
        "alias": _checkbox("attribute_to_sync", connection.sync_alias),
        "email_address": _checkbox("attribute_to_sync", connection.sync_email),
        "pager": _checkbox("attribute_to_sync", connection.sync_pager),
        # Sent even when off, so turning one off is seen as a change.
        "contact_group_membership": {"state": "disabled"},
        "groups_to_roles": {"state": "disabled"},
    }
    if connection.sync_contact_groups:
        plugins["contact_group_membership"] = {
            "state": "enabled",
            "handle_nested": bool(connection.handle_nested_groups),
            "sync_from_other_connections": [],
        }
    if connection.role_mappings:
        roles = {"state": "enabled"}
        # Checkmk only answers with the flag when it is set.
        if connection.handle_nested_groups:
            roles["handle_nested"] = True
        for mapping in connection.role_mappings:
            roles.setdefault(mapping.role, []).append({
                "group_dn": mapping.group_dn,
                "search_in": "this_connection",
            })
        plugins["groups_to_roles"] = roles
    return plugins


def build_payload(connection, account):
    """
    Checkmk API payload of one LDAP Connection.
    ``account`` is the resolved Syncer LDAP Account.
    """
    host, port, use_ssl = _server(account['address'])
    days, minutes = divmod(connection.sync_interval or 5, 1440)
    hours, minutes = divmod(minutes, 60)
    return {
        "general_properties": {
            "id": connection.connection_id,
            "description": connection.description or connection.connection_id,
            "comment": connection.comment or '',
            "rule_activation": "deactivated" if connection.deactivated else "activated",
        },
        "ldap_connection": {
            "directory_type": {
                "type": connection.directory_type,
                "ldap_server": host,
                "failover_servers": list(connection.failover_servers or []),
            },
            "bind_credentials": _bind_credentials(connection, account),
            "tcp_port": {"state": "enabled", "port": port},
            "ssl_encryption": "enable_ssl" if use_ssl else "disable_ssl",
            "connection_suffix": _checkbox("suffix", connection.connection_suffix),
        },
        "users": {
            "user_base_dn": connection.user_base_dn,
            "search_scope": "search_whole_subtree",
            "search_filter": _checkbox("filter", connection.user_search_filter),
            "filter_group": _checkbox("filter", connection.user_filter_group),
            "user_id_attribute": _checkbox("attribute", connection.user_id_attribute),
            "user_id_case": "convert_to_lowercase" if connection.lower_user_ids
                            else "dont_convert_to_lowercase",
            "umlauts_in_user_ids": "keep_umlauts",
            "create_users": connection.create_users,
        },
        "groups": {
            "group_base_dn": connection.group_base_dn or '',
            "search_scope": "search_whole_subtree",
            "search_filter": _checkbox("filter", connection.group_search_filter),
            "member_attribute": _checkbox("attribute", connection.member_attribute),
        },
        "sync_plugins": _sync_plugins(connection),
        "other": {
            "sync_interval": {"days": days, "hours": hours, "minutes": minutes},
        },
    }


def has_changes(wanted, current):
    """
    True when Checkmk differs in any value the payload sets.
    Settings the Syncer does not manage are not compared.
    """
    if isinstance(wanted, dict):
        if not isinstance(current, dict):
            return True
        return any(has_changes(value, current.get(key)) for key, value in wanted.items())
    return wanted != current


def needs_update(payload, current):
    """
    True when Checkmk's connection differs from the payload. The role
    mapping is compared as a whole, so a role taken out is seen too.
    """
    roles = payload['sync_plugins']['groups_to_roles']
    return has_changes(payload, current) or \
        roles != current.get('sync_plugins', {}).get('groups_to_roles')


class CheckmkLdapConnectionSync(CMK2):
    """
    Export LDAP Connections to Checkmk
    """
    name = "Export LDAP Connections to Checkmk"
    source = "cmk_ldap_connection_sync"

    def export_connection(self, connection):
        """
        Create, update or delete one LDAP Connection
        """
        ident = connection.connection_id
        url = f"/objects/ldap_connection/{ident}"
        current, headers = self.request(url, method="GET")
        if connection.remove_if_found:
            if current:
                self.request(url, method="DELETE",
                             additional_header={'if-match': headers['ETag']})
                print(f"{CC.OKGREEN} *{CC.ENDC} {ident}: Deleted")
            return

        account = get_account_by_name(connection.ldap_account)
        payload = build_payload(connection, account)
        if not current:
            self.request("/domain-types/ldap_connection/collections/all",
                         method="POST", data=payload)
            print(f"{CC.OKGREEN} *{CC.ENDC} {ident}: Created")
        elif needs_update(payload, current['extensions']):
            self.request(url, method="PUT", data=payload,
                         additional_header={'if-match': headers['ETag']})
            print(f"{CC.OKGREEN} *{CC.ENDC} {ident}: Updated")
        else:
            print(f"{CC.OKGREEN} *{CC.ENDC} {ident}: Nothing to do")

    def export_ldap_connections(self):
        """
        Export all LDAP Connections. One failing connection does not
        stop the others.
        """
        for connection in CheckmkLdapConnection.objects():
            try:
                self.export_connection(connection)
            except (CmkException, AccountNotFoundError) as error:
                logger.debug("LDAP connection %s failed", connection.connection_id,
                             exc_info=True)
                print(f"{CC.FAIL} *{CC.ENDC} {connection.connection_id}: {error}")
                self.log_details.append(
                    ("ERROR", f"{connection.connection_id}: {error}"))
