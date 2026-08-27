"""LDAP plugin."""
import click

from application import app
from application.helpers.inventory import run_inventory
from application.helpers.cron import register_cronjob
from application.helpers.get_account import get_account_by_name
from application.helpers.plugins import register_cli_group

from .ldap import ldap_import, ldap_debug_query, _inner_import

cli_ldap = register_cli_group(app, 'ldap', 'ldap', "LDAP Import/ Inventorize")

@cli_ldap.command('import_objects')
@click.option("--debug", default=False, is_flag=True)
@click.argument('account')
def cli_ldap_import(account, debug):
    """Import LDAP Objects"""
    ldap_import(account, debug)

@cli_ldap.command('debug_query')
@click.argument('account')
@click.option('--base-dn', '-b', default=None,
              help="Overwrite the Base DN of the Account")
@click.option('--search-filter', '-f', default=None,
              help="Overwrite the Search Filter of the Account")
@click.option('--attributes', '-a', default=None,
              help="Overwrite the Attributes of the Account, empty string for all")
@click.option('--limit', '-l', default=10,
              help="Stop after this many objects, 0 for all")
@click.option("--debug", default=False, is_flag=True)
def cli_ldap_debug_query(account, limit, debug, **overrides):
    """Try out LDAP Queries and Search Filters"""
    ldap_debug_query(account, overrides, limit, debug)


def ldap_inventorize(account, debug=False):
    """
    LDAP Inventorize
    """
    config = get_account_by_name(account)
    config['debug'] = debug
    run_inventory(config, _inner_import(config))


@cli_ldap.command('inventorize_objects')
@click.argument('account')
@click.option("--debug", default=False, is_flag=True)
def cli_ldap_inventorize(account, debug):
    """Inventorize LDAP Objects"""
    ldap_inventorize(account, debug)

register_cronjob("LDAP: Inventorize Data", ldap_inventorize)
register_cronjob("LDAP: Import Objects", ldap_import)
