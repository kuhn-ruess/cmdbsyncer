#!/usr/bin/env python3
"""Import LDAP Data"""
import click
from application import app
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes
from application.helpers.cron import register_cronjob

from application.helpers.inventory import run_inventory

try:
    import ldap
    from ldap.controls.libldap import SimplePagedResultsControl
except ImportError:
    pass

@app.cli.group(name='ldap')
def cli_ldap():
    """LDAP Import/ Inventorize"""


def _inner_import(config):
    """
    Base LDAP Connect and Query
    """
    if not config['address'].startswith('ldap'):
        raise Exception("Address needs to start with ldap:// or ldaps://")

    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{config['name']}{ColorCodes.ENDC}")


    connect = ldap.initialize(config['address'])
    connect.set_option(ldap.OPT_REFERRALS, 0)

    connect.simple_bind_s(config['username'], config['password'])


    scope = ldap.SCOPE_SUBTREE
    base_dn = config['base_dn']
    search_filter = config['search_filter']
    #pylint: disable=consider-using-generator
    attributes = []
    if config['attributes']:
        attributes = list([x.strip() for x in config['attributes'].split(',')])

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
    for dn, entry in results:
        labels = {
            'dn': dn,
        }
        if not isinstance(entry, dict):
            continue

        for key, content in entry.items():
            content = content[0].decode(config['encoding'])
            labels[key] = content

        try:
            hostname = labels[config['hostname_field']]
        except KeyError:
            continue

        yield hostname, labels



def ldap_import(account):
    """
    LDAP Import
    """
    config = get_account_by_name(account)
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

@cli_ldap.command('import_hosts')
@click.argument('account')
def cli_ldap_import(account):
    """Inventorize LDAP Objects"""
    ldap_import(account)

def ldap_inventorize(account):
    """
    LDAP Inventorize
    """
    config = get_account_by_name(account)
    run_inventory(config, _inner_import(config))


@cli_ldap.command('inventorize_hosts')
@click.argument('account')
def cli_ldap_inventorize(account):
    """Inventorize LDAP Data"""
    ldap_inventorize(account)

register_cronjob("LDAP: Inventorize Data", ldap_inventorize)
register_cronjob("LDAP: Import Objects", ldap_import)
