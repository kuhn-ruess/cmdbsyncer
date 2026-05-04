#!/usr/bin/env python3
"""Import ODBC Data"""
# pylint: disable=duplicate-code

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
from application.helpers.sql import (
    build_select_query,
    custom_query_allow_ddl,
    validate_custom_query,
)

try:
    import pypyodbc as pyodbc  # pylint: disable=import-error
except Exception:  # pylint: disable=broad-exception-caught
    # pypyodbc raises OdbcNoLibrary (not ImportError) when libodbc.so is
    # missing — catch broadly so the plugin stays loadable without ODBC.
    logger.info("Info: ODBC Plugin was not able to load required modules")

try:
    import sqlserverport
except Exception:  # pylint: disable=broad-exception-caught
    logger.debug("Info: Serverport module not available")

class ODBC(Plugin):
    """
    ODBC Plugin
    """

    def _innter_sql(self): # pylint: disable=too-many-locals
        """
        Mssql Functions
        """
        try:
            print(f"{cc.OKBLUE}Started {cc.ENDC} with account "\
                  f"{cc.UNDERLINE}{self.config['name']}{cc.ENDC}")

            found_hosts = 0
            logger.debug(
                "ODBC config: %s",
                {k: ('***' if k == 'password' else v) for k, v in self.config.items()},
            )
            serverport = self.config.get('serverport')
            if not serverport:
                serverport = sqlserverport.lookup(self.config['address'], self.config['instance'])
            server = f'{self.config["address"]},{serverport}'
            connect_str = (
                f'DRIVER={{{self.config["driver"]}}};'
                f'SERVER={server};'
                f'DATABASE={self.config["database"]};'
                f'UID={self.config["username"]};'
                f'PWD={self.config["password"]}'
            )
            trust_cert = str(self.config.get('trust_server_certificate', '')).strip().lower()
            if trust_cert in ('yes', 'true', '1'):
                connect_str += ';TrustServerCertificate=YES'
            logger.debug(
                "ODBC connect string: %s",
                connect_str.replace(f'PWD={self.config["password"]}', 'PWD=***'),
            )
            cnxn = pyodbc.connect(connect_str)
            cursor = cnxn.cursor()

            if "custom_query" in self.config and self.config['custom_query']:
                query = validate_custom_query(
                    self.config['custom_query'],
                    allow_ddl=custom_query_allow_ddl(self.config),
                )
            else:
                query = build_select_query(self.config['fields'], self.config['table'])
            logger.debug(query)
            allow_ddl = custom_query_allow_ddl(self.config)
            cursor.execute(query)
            logger.debug("Cursor Executed")
            if allow_ddl:
                # Multi-statement (CREATE …; SELECT …) leaves the cursor
                # on the DDL result set first — walk nextset() until we
                # reach the one that actually has columns.
                while cursor.description is None and cursor.nextset():
                    pass
            rows = cursor.fetchall()
            logger.debug("Fetch Executed: %s", cursor.description)
            columns = [column[0] for column in cursor.description]
            # Commit *after* fetch — on unixODBC a commit between
            # execute() and fetchall() invalidates the open cursor and
            # the next fetch raises HY010 Function sequence error.
            if allow_ddl:
                cursor.close()
                cnxn.commit()
            for row in rows:
                logger.debug("Found row: %s", row)
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
        rewrite = self.config.get('rewrite_hostname')
        entries = []
        for hostname, labels in self._innter_sql():
            # Mirror the import path so inventory writes land on the
            # same host key as the matching importer.
            if rewrite:
                hostname = Host.rewrite_hostname(hostname, rewrite, labels)
            entries.append((hostname, labels))
        run_inventory(self.config, entries)
