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

    print(f"{ColorCodes.OKCYAN}Started {ColorCodes.ENDC} with account "\
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
        if not labels[config['hostname_field']]:
            continue
        hostname = labels[config['hostname_field']].strip().lower()
        if 'rewrite_hostname' in config and config['rewrite_hostname']:
            hostname = Host.rewrite_hostname(hostname, config['rewrite_hostname'], labels)
        if not hostname:
            continue
        print(f" {ColorCodes.OKGREEN}* {ColorCodes.ENDC} Check {hostname}")
        del labels[config['hostname_field']]

        host_obj = Host.get_host(hostname)
        host_obj.update_host(labels)
        do_save = host_obj.set_account(account_dict=config)
        if do_save:
            print(f" {ColorCodes.OKBLUE} * {ColorCodes.ENDC} Updated Labels")
            host_obj.save()
        else:
            print(f" {ColorCodes.WARNING} * {ColorCodes.ENDC} Managed by diffrent master")

def mysql_inventorize(account):
    """
    Inventorize Hosts
    """
    config = get_account_by_name(account)
    print(f"{ColorCodes.OKCYAN}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{config['name']}{ColorCodes.ENDC}")


    key = config['inventorize_key']
    mydb = mysql.connector.connect(
      host=config["address"],
      user=config["username"],
      password=config["password"],
      database=config["database"]
    )
    mycursor = mydb.cursor()
    mycursor.execute(f"SELECT {config['fields']} FROM {config['table']};")
    field_names = config['fields'].split(',')
    for line in mycursor.fetchall():
        labels = dict(zip(field_names, line))
        if not labels[config['hostname_field']]:
            continue
        hostname = labels[config['hostname_field']].strip().lower()
        if not hostname:
            continue
        print(f" {ColorCodes.OKCYAN}* {ColorCodes.ENDC} Check {hostname}")
        del labels[config['hostname_field']]

        host_obj = Host.get_host(hostname, create=False)
        if host_obj:
            host_obj.update_inventory(key, labels)
            print(f" {ColorCodes.OKBLUE} * {ColorCodes.ENDC} Updated Inventory")
            host_obj.save()
        else:
            print(f" {ColorCodes.WARNING} * {ColorCodes.ENDC} Syncer does not have this Host")



@cli_mysql.command('import_hosts')
@click.argument('account')
def cli_mysql_import(account):
    """Import MysQL Hosts"""
    mysql_import(account)

@cli_mysql.command('inventorize_hosts')
@click.argument('account')
def cli_inventorize_hosts(account):
    """
    ## Add Inventory Information to hosts
    Source is a MYSQL. Every Column, will translate
    into key:value attributes.

    ### Example
    _./cmdbsyncer mysql inventorize_hosts ACCOUNTNAME"_

    """
    mysql_inventorize(account)

register_cronjob("Mysql: Import Hosts", mysql_import)
register_cronjob("Mysql: Inventorize Hosts", mysql_inventorize)
