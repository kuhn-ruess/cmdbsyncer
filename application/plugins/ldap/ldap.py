#!/usr/bin/env python3
"""Import LDAP Data"""
# pylint: disable=no-member
from application import log
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes

try:
    import ldap
    from ldap.controls.libldap import SimplePagedResultsControl
except ImportError:
    pass

def get_objects(results, config):
    """
    Get Host Objects
    """
    for dn, entry in results:
        labels = {
            'dn': dn,
        }
        if not isinstance(entry, dict):
            continue

        for key, content in entry.items():
            # LDAP returns each attribute as a list; skip attributes
            # with no values instead of raising IndexError and aborting
            # the whole import.
            if not content:
                continue
            labels[key] = content[0].decode(config['encoding'])

        try:
            hostname = labels[config['hostname_field']]
        except KeyError:
            continue

        if config.get('rewrite_hostname'):
            hostname = Host.rewrite_hostname(hostname, config['rewrite_hostname'], labels)

        yield hostname, labels

def _connect(config):
    """
    Initialize an LDAP connection, upgrade plain ldap:// via StartTLS
    unless explicitly allowed to stay unencrypted, and bind.
    Returns the connection or None on failure.
    """
    connect = ldap.initialize(config['address'])
    connect.set_option(ldap.OPT_REFERRALS, 0)

    if config['address'].lower().startswith('ldap://'):
        try:
            connect.start_tls_s()
        except ldap.LDAPError as tls_error:
            if str(config.get('allow_unencrypted', '')).strip().lower() \
                    not in ('yes', 'true', '1'):
                print("Error: LDAP StartTLS failed and unencrypted bind is "
                      "not allowed for this account")
                log.log(
                    "LDAP import aborted: StartTLS failed and unencrypted "
                    "bind is not allowed for this account",
                    source="LDAP",
                    details=[
                        ("account", config.get('name', '')),
                        ("address", config.get('address', '')),
                        ("error", str(tls_error)),
                    ],
                )
                if config['debug']:
                    raise
                return None
            print(f"Warning: Continuing without TLS ({tls_error})")

    try:
        connect.simple_bind_s(config['username'], config['password'])
    except ldap.SERVER_DOWN:
        print("Error: Ldap Server not reachable")
        if config['debug']:
            raise
        return None
    return connect


def _inner_import(config):
    """
    Base LDAP Connect and Query
    """
    if not config['address'].startswith('ldap'):
        print("Error: Address needs to start with ldap:// or ldaps://")
        if config['debug']:
            raise ValueError("Address needs to start with ldap:// or ldaps://")
        return

    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{config['name']}{ColorCodes.ENDC}")

    connect = _connect(config)
    if connect is None:
        return



    scope = ldap.SCOPE_SUBTREE
    base_dn = config['base_dn']
    search_filter = config['search_filter']
    if config['debug']:
        print(f"INFO: Use Filter: {search_filter}")

    attributes = []
    if config['attributes']:
        attributes = [x.strip() for x in config['attributes'].split(',')]

    if config['debug']:
        print(f"INFO: Search the following Attributes: {attributes}")

    page_control = SimplePagedResultsControl(True, size=1000, cookie='')

    response = connect.search_ext(base_dn,
                                  scope,
                                  search_filter,
                                  attributes,
                                  serverctrls=[page_control])
    results = []
    pages = 0
    while True:
        pages += 1
        _rtype, rdata, _rmsgid, srvctrls = connect.result3(response)
        results.extend(rdata)
        controls = [ctl for ctl in srvctrls \
                       if ctl.controlType == SimplePagedResultsControl.controlType]
        if not controls:
            raise ValueError("The server ignores RFC 2696 control")
        if not controls[0].cookie:
            break

        page_control.cookie = controls[0].cookie
        response = connect.search_ext(base_dn,
                                      scope,
                                      search_filter,
                                      attributes,
                                      serverctrls=[page_control])

    yield from get_objects(results, config)



def ldap_import(account, debug=False):
    """
    LDAP Import
    """
    config = get_account_by_name(account)
    config['debug'] = debug
    for hostname, labels in _inner_import(config):
        print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
        host_obj = Host.get_host(hostname)
        do_save = host_obj.set_account(account_dict=config)
        host_obj.update_host(labels)
        if do_save:
            print(f" {ColorCodes.OKGREEN} * {ColorCodes.ENDC} Updated Labels")
            host_obj.save()
        else:
            print(f" {ColorCodes.WARNING} * {ColorCodes.ENDC} Managed by diffrent master")
