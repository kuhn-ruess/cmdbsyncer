#!/usr/bin/env python3
"""Import Mysql Data"""
from application import logger
from application.models.host import Host
from application.helpers.get_account import get_account_by_name
from application.modules.debug import ColorCodes
from application.helpers.inventory import run_inventory
from application.helpers.sql import (
    build_select_query,
    custom_query_allow_ddl,
    validate_custom_query,
)
try:
    import mysql.connector
except ImportError:
    pass

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
    allow_ddl = custom_query_allow_ddl(config)
    mycursor = mydb.cursor() if not allow_ddl else mydb.cursor(buffered=True)
    if "custom_query" in config and config['custom_query']:
        query = validate_custom_query(config['custom_query'], allow_ddl=allow_ddl)
    else:
        query = build_select_query(config['fields'], config['table'])
    logger.debug(query)
    if allow_ddl:
        # Multi-statement (CREATE …; SELECT …) needs multi=True on
        # mysql.connector. Consume every result set and keep the last
        # one that yields rows for the importer to iterate.
        results = list(mycursor.execute(query, multi=True))
        all_hosts = []
        for stmt_result in results:
            if stmt_result.with_rows:
                all_hosts = stmt_result.fetchall()
        mydb.commit()
    else:
        mycursor.execute(query)
        all_hosts = mycursor.fetchall()
    field_names = config['fields'].split(',')
    for line in all_hosts:
        labels = dict(zip(field_names, line))
        if not labels[config['hostname_field']]:
            continue
        hostname = labels[config['hostname_field']].strip()
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


    mydb = mysql.connector.connect(
      host=config["address"],
      user=config["username"],
      password=config["password"],
      database=config["database"]
    )
    allow_ddl = custom_query_allow_ddl(config)
    mycursor = mydb.cursor() if not allow_ddl else mydb.cursor(buffered=True)
    if "custom_query" in config and config['custom_query']:
        query = validate_custom_query(config['custom_query'], allow_ddl=allow_ddl)
    else:
        query = build_select_query(config['fields'], config['table'])
    if allow_ddl:
        rows = []
        for stmt_result in mycursor.execute(query, multi=True):
            if stmt_result.with_rows:
                rows = stmt_result.fetchall()
        mydb.commit()
    else:
        mycursor.execute(query)
        rows = mycursor.fetchall()
    field_names = config['fields'].split(',')

    objects = []
    rewrite = config.get('rewrite_hostname')
    for line in rows:
        labels = dict(zip(field_names, line))
        if not labels[config['hostname_field']]:
            continue
        hostname = labels[config['hostname_field']].strip()
        if not hostname:
            continue
        del labels[config['hostname_field']]
        # Mirror the import path so inventory writes land on the same
        # host key as the matching importer.
        if rewrite:
            hostname = Host.rewrite_hostname(hostname, rewrite, labels)

        objects.append((hostname, labels))
    run_inventory(config, objects)
