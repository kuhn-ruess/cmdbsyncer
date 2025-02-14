#!/usr/bin/env python3
"""Sync VMware Vsphere Custom Attributes"""
#pylint: disable=logging-fstring-interpolation

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

try:
    from pyVmomi import vim
except ImportError:
    pass

from syncerapi.v1 import (
    Host,
)

from syncerapi.v1.inventory import (
    run_inventory,
)

from application import logger
from application import app
from application.modules.vmware.vmware import VMWareVcenterPlugin


class VMwareCustomAttributesPlugin(VMWareVcenterPlugin):
    """
    VMware Custom Attributes
    """
    console = None
    container_view = None

    def get_vm_attributes(self, vm, content):
        """
        Prepare Attributes
        """
        attributes = {
            "name": vm.name,
            "power_state": vm.runtime.powerState,
        }

        if vm.guest:
            attributes.update({
                "ip_address": vm.guest.ipAddress,
                "hostname": vm.guest.hostName,
                "full_name": vm.guest.guestFullName,
                "tools_status": vm.guest.toolsStatus,
            })
        if vm.config:
            attributes.update({
                "cpu_count": vm.config.hardware.numCPU,
                "memory_mb": vm.config.hardware.memoryMB,
                "guest_os": vm.config.guestFullName,
                "uuid": vm.config.uuid,
                "guest_id": vm.config.guestId,
                "annotation": vm.config.annotation,
                #"hw_device": vm.config.hardware.device,
            })

        if vm.runtime:
            attributes.update({
                 "power_state": vm.runtime.powerState,
                 "runtime_host": vm.runtime.host,
                 "boot_time": vm.runtime.bootTime,
            })

        if vm.network:
            networks = []
            for network in vm.network:
                networks.append({'name': network.name})
            attributes['networks'] = networks

        if vm.datastore:
            datastores = []
            for datastore in vm.datastore:
                datastores.append({'name': datastore.info.name})
            attributes['datastores'] = datastores

        if vm.customValue:
            for custom_field in vm.customValue:
                field_key = custom_field.key
                field_name = next(
                    (f.name for f in content.customFieldsManager.field if f.key == field_key),
                    f"custom_{field_key}"
                )
                attributes[field_name] = custom_field.value

        return_dict = {}
        for key, value in attributes.items():
            if not isinstance(value, str) and not isinstance(value, list):
                value = str(value)
            return_dict[key] = value

        return return_dict


    def get_current_attributes(self):
        """
        Return list of all Objects
        and their Attributes
        """
        content = self.vcenter.RetrieveContent()
        container = content.viewManager.CreateContainerView(content.rootFolder,
                                                            [vim.VirtualMachine], True)
        self.container_view = container.view
        data = [self.get_vm_attributes(x, content) for x in self.container_view]
        return data


    def export_attributes(self):
        """
        Export Custom Attributes
        """
        self.connect()
        current_attributes = {x['name']:x for x in self.get_current_attributes()}

        current_vms = {x.name:x for x in self.container_view}

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
                    all_attributes = self.get_host_attributes(db_host, 'vmware_vcenter')
                    if not all_attributes:
                        progress.advance(task1)
                        continue
                    custom_rules = self.get_host_data(db_host, all_attributes['all'])
                    if not custom_rules:
                        progress.advance(task1)
                        continue

                    self.console(f" * Work on {hostname}")
                    logger.debug(f"{hostname}: {custom_rules}")
                    changes = []
                    if vm_host_data := current_attributes.get(hostname):
                        for new_attr_name, new_attr_value in custom_rules['attributes'].items():
                            old_value = False
                            if old_attr := vm_host_data.get(new_attr_name):
                                old_value = old_attr
                            if old_value != new_attr_value:
                                changes.append(f"{new_attr_name}: {old_attr} to {new_attr_value}")
                                current_vms[hostname].SetCustomValue(key=new_attr_name,
                                                                     value=new_attr_value)
                        logger.debug(f" Updated: {changes}")
                    else:
                        logger.debug(f" Not found in VMware Data")
                        progress.advance(task1)
                        continue

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
        run_inventory(self.config, [(x['name'], x) for x in self.get_current_attributes()])
