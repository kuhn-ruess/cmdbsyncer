#!/usr/bin/env python3
"""Import Mysql Data"""
import click
from application import app
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes
import mysql.connector

@app.cli.group(name='mysql')
def cli_mysql():
    """MYSQL Related commands"""

@cli_mysql.command('import_hosts')
@click.argument('account')
def mysql_import(account):
    """Import MysQL Hosts"""

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
        hostname = labels['host_hostname'].strip().lower()
        print(f" {ColorCodes.OKGREEN}* {ColorCodes.ENDC} Check {hostname}")
        labels = dict(zip(field_names, line))
        del labels['host_hostname']

        host_obj = Host.get_host(hostname)
        host_obj.set_import_seen()
        if host_obj.get_labels() == labels:
            host_obj.set_labels(labels)
        if host_obj.set_account(account_dict=config):
            print(f" {ColorCodes.OKGREEN} * {ColorCodes.ENDC} Updated Labels")
            host_obj.save()
            continue
        print(f" {ColorCodes.WARNING} * {ColorCodes.ENDC} Managed by diffrent master")
