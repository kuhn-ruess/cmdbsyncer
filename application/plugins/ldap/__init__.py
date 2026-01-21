import click

from application import app
from application.helpers.inventory import run_inventory
from application.helpers.cron import register_cronjob

from .ldap import ldap_import, _inner_import

@app.cli.group(name='ldap')
def cli_ldap():
    """LDAP Import/ Inventorize"""

@cli_ldap.command('import_objects')
@click.option("--debug", default=False, is_flag=True)
@click.argument('account')
def cli_ldap_import(account, debug):
    """Import LDAP Objects"""
    ldap_import(account, debug)

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