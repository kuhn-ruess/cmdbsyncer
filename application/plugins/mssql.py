#!/usr/bin/env python3
"""Import mssl Data"""
#pylint: disable=logging-fstring-interpolation
import click
from application import app, logger
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes as CC
from application.helpers.cron import register_cronjob
try:
    import pypyodbc as pyodbc
    import sqlserverport
except ImportError:
    logger.debug("Info: Mssql Plugin was not able to load required modules")

@app.cli.group(name='mssql')
def cli_mssql():
    """Mssql Related commands"""


def _innter_sql(config):
    """
    Mssql Functions
    """
    try:

        print(f"{CC.OKBLUE}Started {CC.ENDC} with account "\
              f"{CC.UNDERLINE}{config['name']}{CC.ENDC}")


        logger.debug(config)
        serverport = config.get('serverport')
        if not serverport:
            serverport = sqlserverport.lookup(config['address'], config['instance'])
        server = f'{config["address"]},{serverport}'
        connect_str = f'DRIVER={{{config["driver"]}}};SERVER={server};'\
                      f'DATABASE={config["database"]};UID={config["username"]};'\
                      f'PWD={config["password"]};TrustServerCertificate=YES'
        logger.debug(connect_str)
        cnxn = pyodbc.connect(connect_str)
        cursor = cnxn.cursor()
        query = f"select {config['fields']} from {config['table']};"
        if "custom_query" in config and config['custom_query']:
            query = config['custom_query']
        logger.debug(query)
        cursor.execute(query)
        logger.debug("Cursor Executed")
        rows = cursor.fetchall()
        for row in rows:
            logger.debug(f"Found row: {row}")
            labels=dict(zip(config['fields'].split(","),row))
            hostname = labels[config['hostname_field']].strip()
            if 'rewrite_hostname' in config and config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname, config['rewrite_hostname'], labels)
            yield hostname, labels
    except NameError as error:
        print(f"EXCEPTION: Missing requirements, pypyodbc or sqlserverport ({error})")

def mssql_import(account):
    """
    Mssql Import
    """
    config = get_account_by_name(account)
    for hostname, labels in _innter_sql(config):
        print(f" {CC.OKGREEN}* {CC.ENDC} Check {hostname}")
        del labels[config['hostname_field']]
        host_obj = Host.get_host(hostname)
        host_obj.update_host(labels)
        do_save=host_obj.set_account(account_dict=config)
        if do_save:
            host_obj.save()
        else:
            print(f" {CC.WARNING} * {CC.ENDC} Managed by diffrent master")


def _innter_inventorize(host_obj, labels, key, config):
    """
    Add Inventorize Information to host
    """
    if host_obj:
        attr_match = config.get('inventorize_match_attribute')
        if attr_match:
            try:
                attr_value = host_obj.get_labels()[attr_match]
                inv_attr_value= labels[attr_match]
                if attr_value != inv_attr_value:
                    print(f" {CC.WARNING} * {CC.ENDC} Attribute '{attr_match}' "\
                          f"is '{attr_value}' but '{inv_attr_value}' in source.")
                    return
            except KeyError as error:
                print(f" {CC.WARNING} * {CC.ENDC} Cant match Attribute."
                      f" Host has no Label {attr_match} ({error})")

        host_obj.update_inventory(key, labels)
        print(f" {CC.OKBLUE} * {CC.ENDC} Updated Inventory")
        host_obj.save()
    else:
        print(f" {CC.WARNING} * {CC.ENDC} Syncer does not have this Host")

@cli_mssql.command('import_hosts')
@click.argument('account')
def cli_mssql_import(account):
    """Import MSSQL Hosts"""
    mssql_import(account)

def mssql_inventorize(account):
    """
    Mssql Inventorize
    """
    config = get_account_by_name(account)
    key = config['inventorize_key']
    for hostname, labels in _innter_sql(config):
        if config.get('inventorize_match_by_domain'):
            for host_obj in Host.objects(hostname__endswith=hostname):
                _innter_inventorize(host_obj, labels, key, config)
        else:
            host_obj = Host.get_host(hostname, create=False)
            _innter_inventorize(host_obj, labels, key, config)


@cli_mssql.command('inventorize_hosts')
@click.argument('account')
def cli_mssql_inveninveninveninveninveninveninveninveninventorize(account):
    """Inventorize MSSQL Data"""
    mssql_inventorize(account)

register_cronjob("MSSql: Import Hosts", mssql_import)
register_cronjob("MSSql: Inventorize Data", mssql_inventorize)
