#!/usr/bin/env python3
"""Import LDAP Data"""
# pylint: disable=no-member
import re

from application import log
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes, attribute_table

try:
    import ldap
    from ldap.controls.libldap import SimplePagedResultsControl
    from ldap.filter import escape_filter_chars
    LDAP_AVAILABLE = True
except ImportError:
    LDAP_AVAILABLE = False


class LdapSearchError(Exception):
    """
    A search could not be executed. The message is meant to be shown to
    the user, so it carries the reason the server or the account gave.
    """


# Attribute names as LDAP allows them — anything else in a search would
# end up unescaped in the filter
ATTRIBUTE_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9-]*$')


def _require_ldap():
    """
    Stop with a readable message when python-ldap is missing
    """
    if not LDAP_AVAILABLE:
        raise LdapSearchError("The python-ldap module is not installed on this server")


def decode_value(value, config):
    """
    One attribute value as text, with the encoding of the account.

    The import decodes strictly, so a wrong encoding is not silently
    imported as broken data. The diagnostic paths (search, debug_query)
    set `encoding_errors` to 'replace' instead: they are the place where
    the wrong encoding is supposed to become visible, not the place to
    stop working because of it.
    """
    return value.decode(config['encoding'], errors=config.get('encoding_errors', 'strict'))


# Character a value carries where it could not be decoded
REPLACEMENT_CHARACTER = '\ufffd'

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
            labels[key] = decode_value(content[0], config)

        try:
            hostname = labels[config['hostname_field']]
        except KeyError:
            continue

        if config.get('rewrite_hostname'):
            hostname = Host.rewrite_hostname(hostname, config['rewrite_hostname'], labels)

        yield hostname, labels


def parse_object(dn, entry, config):
    """
    One raw LDAP result the way the import sees it.

    Returns (hostname, labels). The hostname is empty when the object has
    no hostname field — then the labels carry every attribute the object
    has, so it is visible why it would be skipped.
    """
    parsed = list(get_objects([(dn, entry)], config))
    if parsed:
        return parsed[0]

    labels = {key: ', '.join(decode_value(x, config) for x in content)
              for key, content in entry.items()}
    labels['dn'] = dn
    return '', labels


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


def _check_address(config):
    """
    Make sure the account points to an ldap server
    """
    if not config['address'].startswith('ldap'):
        print("Error: Address needs to start with ldap:// or ldaps://")
        if config['debug']:
            raise ValueError("Address needs to start with ldap:// or ldaps://")
        return False
    return True


def _get_attributes(config):
    """
    Attributes to request, empty list means all of them
    """
    if config['attributes']:
        return [x.strip() for x in config['attributes'].split(',')]
    return []


def _search(connect, config, limit=0):
    """
    Paged LDAP Search, yields the raw (dn, entry) tuples
    """
    query = (config['base_dn'], ldap.SCOPE_SUBTREE,
             config['search_filter'], _get_attributes(config))

    if config['debug']:
        print(f"INFO: Use Filter: {query[2]}")
        print(f"INFO: Search the following Attributes: {query[3]}")

    page_control = SimplePagedResultsControl(True, size=1000, cookie='')

    response = connect.search_ext(*query, serverctrls=[page_control])
    found = 0
    while True:
        _rtype, rdata, _rmsgid, srvctrls = connect.result3(response)
        for result in rdata:
            yield result
            found += 1
            if limit and found >= limit:
                return
        controls = [ctl for ctl in srvctrls \
                       if ctl.controlType == SimplePagedResultsControl.controlType]
        if not controls:
            raise ValueError("The server ignores RFC 2696 control")
        if not controls[0].cookie:
            break

        page_control.cookie = controls[0].cookie
        response = connect.search_ext(*query, serverctrls=[page_control])


def build_search_filter(config, mode, term, attribute=None, use_account_filter=True):
    """
    Build the LDAP filter of a single search.

    Modes:
        hostname   the hostname field of the account, with or without a
                   domain: 'srv01' also finds 'srv01.example.com'
        contains   the hostname field contains the term anywhere
        attribute  the given attribute contains the term
        filter     the term already is an LDAP filter and is used as it is

    Unless `use_account_filter` is off, the search filter of the account is
    combined with the term, so only the objects the account works with are
    searched.
    """
    _require_ldap()
    term = term.strip()
    if not term:
        raise LdapSearchError("Enter something to search for")

    if mode == 'filter':
        query = term if term.startswith('(') else f"({term})"
    else:
        value = escape_filter_chars(term)
        field = config['hostname_field']
        if mode == 'hostname':
            # Either the name itself, or the name with any domain behind it
            query = f"(|({field}={value})({field}={value}.*))"
        elif mode == 'contains':
            query = f"({field}=*{value}*)"
        elif mode == 'attribute':
            attribute = (attribute or '').strip()
            if not ATTRIBUTE_NAME.match(attribute):
                raise LdapSearchError(f"'{attribute}' is not an attribute name")
            query = f"({attribute}=*{value}*)"
        else:
            raise LdapSearchError(f"Unknown search mode '{mode}'")

    account_filter = (config.get('search_filter') or '').strip()
    if use_account_filter and account_filter and account_filter != query:
        query = f"(&{account_filter}{query})"
    return query


def search_objects(config, search_filter, limit=25):
    """
    Run one search and return the found objects as
    [{'dn':, 'hostname':, 'labels':}] — the hostname is empty for objects
    the import would skip. Raises LdapSearchError with the reason if the
    search could not be done.
    """
    _require_ldap()

    # debug lets the connection errors travel up instead of just being
    # printed, so the reason can be shown instead of an empty result
    config = dict(config, debug=True, search_filter=search_filter,
                  encoding_errors='replace')
    try:
        _check_address(config)
        connect = _connect(config)
        if connect is None:
            raise LdapSearchError("Could not connect to the LDAP server")
        # The query itself has no console to print its debug output to
        config['debug'] = False
        results = []
        for dn, entry in _search(connect, config, limit=limit):
            if not isinstance(entry, dict):
                # Referral, not an object
                continue
            hostname, labels = parse_object(dn, entry, config)
            results.append({'dn': dn, 'hostname': hostname, 'labels': labels})
        return results
    except LookupError as error:
        raise LdapSearchError(f"Unknown encoding '{config['encoding']}'") from error
    except (ldap.LDAPError, ValueError) as error:
        raise LdapSearchError(str(error)) from error


def _inner_import(config):
    """
    Base LDAP Connect and Query
    """
    if not _check_address(config):
        return

    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{config['name']}{ColorCodes.ENDC}")

    connect = _connect(config)
    if connect is None:
        return

    yield from get_objects(_search(connect, config), config)


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


def _print_object(number, dn, entry, config):
    """
    Print one found LDAP Object, returns if it would be imported
    """
    if not isinstance(entry, dict):
        print(f"{ColorCodes.WARNING} * {ColorCodes.ENDC} Referral, no object: {dn}")
        return False

    # Same path the import uses, so the output is what would be imported
    hostname, labels = parse_object(dn, entry, config)
    if hostname:
        attribute_table(f"{number}: {hostname}", labels)
        return True

    attribute_table(f"{number}: IGNORED, no attribute '{config['hostname_field']}'", labels)
    return False


def _collect_attributes(stats, entry, config):
    """
    Count the attributes of one object for the attribute overview
    """
    if not isinstance(entry, dict):
        return
    for key, content in entry.items():
        stat = stats.setdefault(key, {'objects': 0, 'multi': 0, 'example': ''})
        stat['objects'] += 1
        if len(content) > 1:
            stat['multi'] += 1
        if not stat['example'] and content:
            stat['example'] = decode_value(content[0], config)


def _print_attributes(stats, total):
    """
    Print which attributes the objects of the result have
    """
    overview = {}
    for name, stat in sorted(stats.items(), key=lambda x: (-x[1]['objects'], x[0])):
        line = f"in {stat['objects']} of {total} objects"
        if stat['multi']:
            line += f", more than one value in {stat['multi']} (only the first is imported)"
        overview[name] = f"{line}, e.g. {stat['example']}"
    attribute_table(f"Attributes found in {total} objects", overview)
    print("Attributes for the account: " + ','.join(sorted(stats)))
    print()


def ldap_debug_query(account, overrides=None, limit=10, debug=False, list_attributes=False):
    """
    Try out Queries and Search Filters of an LDAP Account
    """
    config = get_account_by_name(account)
    config['debug'] = debug
    # A wrong encoding is one of the things this command is meant to show,
    # so it may not stop the output
    config['encoding_errors'] = 'replace'
    if list_attributes:
        # Attributes can only be shown if the server was asked for all of them
        config['attributes'] = ''
    config.update({k: v for k, v in (overrides or {}).items() if v is not None})

    if not _check_address(config):
        return

    attribute_table("Query", {
        'Account': config['name'],
        'Address': config['address'],
        'Base DN': config['base_dn'],
        'Search Filter': config['search_filter'],
        'Attributes': config['attributes'] or 'all',
        'Hostname Field': config['hostname_field'],
        'Limit': str(limit) if limit else 'no limit',
    })

    connect = _connect(config)
    if connect is None:
        return

    total = 0
    usable = 0
    stats = {}
    try:
        for dn, entry in _search(connect, config, limit=limit):
            total += 1
            if list_attributes:
                _collect_attributes(stats, entry, config)
                continue
            if _print_object(total, dn, entry, config):
                usable += 1
    except ldap.LDAPError as error:
        print(f"{ColorCodes.FAIL}LDAP Error: {error}{ColorCodes.ENDC}")
        if debug:
            raise
        return

    if list_attributes:
        _print_attributes(stats, total)
        print(f"{ColorCodes.OKGREEN}Found {total} objects{ColorCodes.ENDC}")
    else:
        print(f"{ColorCodes.OKGREEN}Found {total} objects, "\
              f"{usable} of them would be imported{ColorCodes.ENDC}")
    if limit and total >= limit:
        print(f"{ColorCodes.WARNING}Output stopped at the limit of {limit} objects, "\
              f"use --limit to see more{ColorCodes.ENDC}")
