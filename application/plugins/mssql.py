#!/usr/bin/env python3
"""Import mssl Data"""
import click
from application import app
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes
from application.helpers.cron import register_cronjob
try:
    import pypyodbc as pyodbc
    import sqlserverport
except:
    pass

@app.cli.group(name='mssql')
def cli_mssql():
    """Mssql Related commands"""

def mssql_import(account):
    """
    Mssql Import
    """
    config = get_account_by_name(account)

    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{config['name']}{ColorCodes.ENDC}")

    serverport = sqlserverport.lookup(config['address'], config['instance'])
    server = f'{config["address"]},{serverport}'
    connect_str = f'DRIVER={{{config["driver"]}}};SERVER={server};DATABASE={config["database"]};UID={config["username"]};PWD={config["password"]};TrustServerCertificate=YES'
    cnxn = pyodbc.connect(connect_str)
    cursor = cnxn.cursor()
    cursor.execute(f"select {config['fields']} from {config['table']};")
    rows = cursor.fetchall()
    for row in rows:
        labels=dict(zip(config['fields'].split(","),row))
        hostname = labels[config['hostname_field']].strip().lower()
        print(f" {ColorCodes.OKGREEN}* {ColorCodes.ENDC} Check {hostname}")
        del labels[config['hostname_field']]
        host_obj = Host.get_host(hostname)
        host_obj.update_host(labels)
        do_save=host_obj.set_account(account_dict=config)
        if do_save:
            host_obj.save()
        else:
            print(f" {ColorCodes.WARNING} * {ColorCodes.ENDC} Managed by diffrent master")

@cli_mssql.command('import_hosts')
@click.argument('account')
def cli_mssql_import(account):
    """Import MSSQL Hosts"""
    mssql_import(account)

register_cronjob("MSSql: Import Hosts", mssql_import)
