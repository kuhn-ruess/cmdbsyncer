#!/usr/bin/env python3
"""
Mysql Import Script
"""
import click
from application import app
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes

import mysql.connector


@app.cli.group(name='NAME')
def cli_example():
    """Commands from NAME"""

@cli_example.command('import_mysql')
@click.argument('account')
def mysql_import(account):
    """Import MysQL Hosts"""

    config = get_account_by_name(account)

    print(config)


    print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
          f"{ColorCodes.UNDERLINE}{account_name}{ColorCodes.ENDC}")

    mydb = mysql.connector.connect(
      host="localhost",
      user="yourusername",
      password="yourpassword"
    )

    mycursor = mydb.cursor()
    mycursor.execute("SELECT * FROM customers")

    all_hosts = mycursor.fetchall()

    for host in all_hosts:
        hostname = ""
        labels = {}

        print(f" {ColorCodes.OKGREEN}** {ColorCodes.ENDC} Update {hostname}")
        host_obj = Host.get_host(hostname)
        if not host_obj.need_import_sync(12):
            continue

        host_obj.set_import_seen()

        if host_obj.get_labels() == labels:
            host_obj.save()
            continue

        #host_obj.set_import_sync()



        host_obj.set_account(account=config)

        host_obj.set_labels(labels)

        host_obj.save()
        print("   * Done")

    return 0
