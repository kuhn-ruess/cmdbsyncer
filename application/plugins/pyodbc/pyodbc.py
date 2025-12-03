#!/usr/bin/env python3
"""Import ODBC Data"""
#pylint: disable=logging-fstring-interpolation

from syncerapi.v1 import (
    cc,
    Host,
)

from syncerapi.v1.core import (
    logger,
    app_config,
    Plugin,
)
from syncerapi.v1.inventory import run_inventory

try:
    import pypyodbc as pyodbc
except: #pylint: disable=bare-except
    logger.info("Info: ODBC Plugin was not able to load required modules")

try:
    import sqlserverport
except ImportError:
    logger.debug("Info: Serverport module not available")

class ODBC(Plugin):
    """
    ODBC Plugin
    """

    def _innter_sql(self):
        """
        Mssql Functions
        """
        try:
            print(f"{cc.OKBLUE}Started {cc.ENDC} with account "\
                  f"{cc.UNDERLINE}{self.config['name']}{cc.ENDC}")

            found_hosts = 0
            logger.debug(self.config)
            serverport = self.config.get('serverport')
            if not serverport:
                serverport = sqlserverport.lookup(self.config['address'], self.config['instance'])
            server = f'{self.config["address"]},{serverport}'
            connect_str = f'DRIVER={{{self.config["driver"]}}};SERVER={server};'\
                          f'DATABASE={self.config["database"]};UID={self.config["username"]};'\
                          f'PWD={self.config["password"]};TrustServerCertificate=YES'
            logger.debug(connect_str)
            cnxn = pyodbc.connect(connect_str)
            cursor = cnxn.cursor()

            if "custom_query" in self.config and self.config['custom_query']:
                query = self.config['custom_query']
            else:
                query = f"select {self.config['fields']} from {self.config['table']};"
            logger.debug(query)
            cursor.execute(query)
            logger.debug("Cursor Executed")
            rows = cursor.fetchall()
            logger.debug(f"Fetch Executed: {cursor.description}")
            columns = [column[0] for column in cursor.description]
            for row in rows:
                logger.debug(f"Found row: {row}")
                labels=dict(zip(columns,row))
                hostname = labels[self.config['hostname_field']].strip()
                if app_config['LOWERCASE_HOSTNAMES']:
                    hostname = hostname.lower()
                found_hosts += 1
                yield hostname, labels
            self.log_details.append(("found_hosts", found_hosts))
        except NameError as error:
            print(f"EXCEPTION: Missing requirements, pypyodbc or sqlserverport ({error})")

    def sql_import(self):
        """
        ODBC Import
        """
        for hostname, labels in self._innter_sql():
            if 'rewrite_hostname' in self.config and self.config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname,
                                                 self.config['rewrite_hostname'], labels)
            print(f" {cc.OKGREEN}* {cc.ENDC} Check {hostname}")
            del labels[self.config['hostname_field']]
            host_obj = Host.get_host(hostname)
            host_obj.update_host(labels)
            do_save=host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
            else:
                print(f" {cc.WARNING} * {cc.ENDC} Managed by diffrent master")

    def sql_inventorize(self):
        """
        ODBC Inventorize
        """
        run_inventory(self.config, self._innter_sql())