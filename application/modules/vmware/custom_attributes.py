#!/usr/bin/env python3
"""Import JDISC Data"""
#pylint: disable=logging-fstring-interpolation
import ssl

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from syncerapi.v1 import (
    Host,
)

from syncerapi.v1.inventory import (
    run_inventory,
)

from syncerapi.v1.core import (
    Plugin,
)

from application import logger
from application import app

try:
    from pyVmomi import vim
    from pyVim.connect import SmartConnect, Disconnect
except ImportError:
    logger.info("Info: VMware Plugin was not able to load required modules")

class VMwareCustomAttributesPlugin(Plugin):
    """
    VMware Custom Attributes
    """
    console = None
    vcenter = None


    def connect(self):
        """
        Connect to VMware
        """
        if app.config.get('DISABLE_SSL_ERRORS'):
            # pylint: disable=protected-access
            context = ssl._create_unverified_context()
        else:
            context = ssl.create_default_context()

        self.vcenter = SmartConnect(host=self.config['address'],
                                    user=self.config['username'],
                                    pwd=self.config['password'],
                                    sslContext=context)
        if not self.vcenter:
            raise Exception("Cannot connect to vcenter")


    def get_current_attributes(self):
        """
        Return list of all Objects
        and their Attributes
        """
        content = self.vcenter.RetrieveContent()
        container = content.viewManager.CreateContainerView(content.rootFolder,
                                                            [vim.VirtualMachine], True)
        data = [ x for x in container.view]
        import pprint

        pprint.pprint(data)
        return []


    def export_attributes(self):
        """
        Export Custom Attributes
        """
        self.connect()
        current_attributes = self.get_current_attributes()

        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Updating Attributes", total=total)
            hostname = None
            for db_host in db_objects:
                try:
                    hostname = db_host.hostname
                    all_attributes = self.get_host_attributes(db_host, 'netbox')
                    if not all_attributes:
                        progress.advance(task1)
                        continue
                    custom_rules = self.get_host_data(db_host, all_attributes['all'])
                    if not custom_rules:
                        progress.advance(task1)
                        continue

                    self.console(f" * Work on {hostname}")
                    logger.debug(f"{hostname}: {custom_rules}")
                except Exception as error:
                    if self.debug:
                        raise
                    self.log_details.append((f'export_error {hostname}', str(error)))
                    self.console(f" Error in process: {error}")
                progress.advance(task1)


    def inventorize_attributes(self):
        """
        Inventorize Custom Attributes
        """
        self.connect()

        run_inventory(self.config, [(x.name, {str(y):str(z) for y,z in x.__dict__.items()}) for x in self.get_current_attributes()])
