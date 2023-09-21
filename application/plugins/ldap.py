#!/usr/bin/env python3
"""Import LDAP Data"""
import click
from application import app
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes
from application.helpers.cron import register_cronjob


try:
    import ldap
except ImportError:
    pass

@app.cli.group(name='ldap')
def cli_ldap():
    """LDAP Related commands"""

def ldap_import(account):
    """
    LDAP Import
    """
    config = get_account_by_name(account)
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
    attributes = list([x.strip() for x in config['attributes'].split(',')])

    result = connect.search_s(base_dn,
                              scope,
                              search_filter,
                              attributes)
    for _dn, entry in result:
        print(entry)

        #hostname = labels['host_hostname'].strip().lower()
        #print(f" {ColorCodes.OKGREEN}* {ColorCodes.ENDC} Check {hostname}")
        #labels = dict(zip(field_names, line))
        #del labels['host_hostname']

        #host_obj = Host.get_host(hostname)
        #do_save = host_obj.set_account(account_dict=config)
        #if do_save:
        #    print(f" {ColorCodes.OKGREEN} * {ColorCodes.ENDC} Updated Labels")
        #    host_obj.save()
        #else:
        #    print(f" {ColorCodes.WARNING} * {ColorCodes.ENDC} Managed by diffrent master")

@cli_ldap.command('import_hosts')
@click.argument('account')
def cli_ldap_import(account):
    """Import LDAP Objects"""
    ldap_import(account)

register_cronjob("LDAP: Import Objects", ldap_import)
