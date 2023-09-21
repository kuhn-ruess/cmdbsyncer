#!/usr/bin/env python3
"""Import Mysql Data"""
import click
from application import app
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes
from application.helpers.cron import register_cronjob
try:
    import mysql.connector
except ImportError:
    pass

@app.cli.group(name='mysql')
def cli_mysql():
    """MYSQL Related commands"""

def mysql_import(account):
    """
    Mysql Import
    """
    config = get_account_by_name(account)

    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{config['name']}{ColorCodes.ENDC}")

    mydb = mysql.connector.connect(
      host=config["address"],
      user=config["username"],
      password=config["password"],
      database=config["database"]
    )
    mycursor = mydb.cursor()
    mycursor.execute(f"SELECT {config['fields']} FROM {config['table']};")
    all_hosts = mycursor.fetchall()
    field_names = config['fields'].split(',')
    for line in all_hosts:
        labels = dict(zip(field_names, line))
        hostname = labels[config['hostname_field']].strip().lower()
        print(f" {ColorCodes.OKGREEN}* {ColorCodes.ENDC} Check {hostname}")
        del labels[config['hostname_field']]

        host_obj = Host.get_host(hostname)
        host_obj.update_host(labels)
        do_save = host_obj.set_account(account_dict=config)
        if do_save:
            print(f" {ColorCodes.OKGREEN} * {ColorCodes.ENDC} Updated Labels")
            host_obj.save()
        else:
            print(f" {ColorCodes.WARNING} * {ColorCodes.ENDC} Managed by diffrent master")

@cli_mysql.command('import_hosts')
@click.argument('account')
def cli_mysql_import(account):
    """Import MysQL Hosts"""
    mysql_import(account)

register_cronjob("Mysql: Import Hosts", mysql_import)
