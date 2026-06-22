#!/usr/bin/env python3
"""Sync VMware Vsphere Custom Attributes"""
from collections import defaultdict

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
from .vmware import VMWareVcenterPlugin


class VMwareCustomAttributesPlugin(VMWareVcenterPlugin):
    """
    VMware Custom Attributes
    """
    console = None
    container_view = None

    def _collect_hardware_devices(self, vm):
        """Group virtual hardware into disks, network cards and controllers"""
        virtual_disks = []
        network_cards = []
        ide_controllers = []
        scsi_controllers = []

        scsi_controller_types = (
            vim.vm.device.ParaVirtualSCSIController,
            vim.vm.device.VirtualLsiLogicSASController,
            vim.vm.device.VirtualLsiLogicController,
            vim.vm.device.VirtualBusLogicController,
        )
        network_controller_types = (
            vim.vm.device.VirtualVmxnet3,
            vim.vm.device.VirtualE1000e,
            vim.vm.device.VirtualE1000,
            vim.vm.device.VirtualVmxnet,
        )

        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualDisk):
                capacity = f"{device.capacityInKB / 1024 / 1024:.2f} GB"
                virtual_disks.append({
                    'id': device.unitNumber,
                    'capacity': capacity,
                    'name': device.deviceInfo.label,
                    'filename': device.backing.fileName,
                    'controllerkey': device.controllerKey,
                })
            elif isinstance(device, network_controller_types):
                network_cards.append({
                    'name': device.deviceInfo.label,
                    'network': device.deviceInfo.summary,
                    'macaddress': device.macAddress,
                })
            elif isinstance(device, vim.vm.device.VirtualIDEController):
                ide_controllers.append({'name': device.deviceInfo.label})
            elif isinstance(device, scsi_controller_types):
                scsi_controllers.append({
                    'name': device.deviceInfo.label,
                    'type': device.deviceInfo.summary,
                    'id': device.unitNumber,
                    'bus': device.busNumber,
                })

        return {
            'network_cards': network_cards,
            'virtual_disks': virtual_disks,
            'ide_controllers': ide_controllers,
            'scsi_controllers': scsi_controllers,
        }

    def get_vm_attributes(self, vm, content):
        """
        Prepare Attributes
        """
        # Resolve a readable resource-pool name from the internal reference
        res_pool_name = vm.resourcePool.name if vm.resourcePool else "Default"

        attributes = {
            "name": vm.name,
            "resource_pool": res_pool_name,
        }

        if vm.guest:
            attributes.update({
                "ip_address": vm.guest.ipAddress,
                "hostname": vm.guest.hostName,
                "full_name": vm.guest.guestFullName,
                "tools_status": vm.guest.toolsStatus,
                "tools_version": vm.guest.toolsVersion,
            })
        if vm.config:
            attributes.update({
                "cpu_count": vm.config.hardware.numCPU,
                "network_card_count": vm.summary.config.numEthernetCards,
                "virtual_disk_count": vm.summary.config.numVirtualDisks,
                "memory_mb": vm.config.hardware.memoryMB,
                "guest_os": vm.config.guestFullName,
                "uuid": vm.config.uuid,
                "guest_id": vm.config.guestId,
                "annotation": vm.config.annotation,
            })

        if vm.runtime:
            attributes.update({
                 "power_state": vm.runtime.powerState,
                 # Readable ESXi host name instead of the internal MoRef
                 "runtime_host": vm.runtime.host.summary.config.name \
                                 if vm.runtime.host else None,
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

        if vm.config and vm.config.hardware.device:
            attributes.update(self._collect_hardware_devices(vm))

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
        Return all VMs and their Attributes, limited to those matching the
        ``inventory_filter`` account setting (``key:value,key:value``).
        """
        inventory_filter = defaultdict(list)
        for pair in (self.config.get('inventory_filter') or '').split(','):
            if ':' in pair:
                key, value = pair.split(':', 1)
                inventory_filter[key.strip()].append(value.strip())

        content = self.vcenter.RetrieveContent()
        container = content.viewManager.CreateContainerView(content.rootFolder,
                                                            [vim.VirtualMachine], True)
        self.container_view = container.view
        data = []
        for vm in self.container_view:
            attributes = self.get_vm_attributes(vm, content)
            if all(str(attributes.get(key)) in values
                   for key, values in inventory_filter.items()):
                data.append(attributes)
        return data


    # pylint: disable-next=too-many-locals
    def export_attributes(self):
        """
        Export Custom Attributes
        """
        self.connect()
        current_attributes = {x['name']:x for x in self.get_current_attributes()}

        # Keep the VM handles in step with the filtered attribute set above,
        # so the export only touches VMs that passed the inventory_filter.
        current_vms = {x.name:x for x in self.container_view
                       if x.name in current_attributes}

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
                    all_attributes = self.get_attributes(db_host, 'vmware_vcenter')
                    if not all_attributes:
                        progress.advance(task1)
                        continue
                    custom_rules = self.get_host_data(db_host, all_attributes['all'])
                    if not custom_rules:
                        progress.advance(task1)
                        continue

                    self.console(f" * Work on {hostname}")
                    logger.debug("%s: %s", hostname, custom_rules)
                    changes = []
                    if vm_host_data := current_attributes.get(hostname):
                        for new_attr_name, new_attr_value in custom_rules['attributes'].items():
                            old_value = vm_host_data.get(new_attr_name) or False
                            if old_value != new_attr_value:
                                # Reference old_value here — old_attr only
                                # existed on the truthy branch of the walrus
                                # and triggered UnboundLocalError when a
                                # previous value was missing or falsy.
                                changes.append(
                                    f"{new_attr_name}: {old_value} to {new_attr_value}"
                                )
                                current_vms[hostname].SetCustomValue(key=new_attr_name,
                                                                     value=new_attr_value)
                        logger.debug(" Updated: %s", changes)
                    else:
                        logger.debug(" Not found in VMware Data")
                        progress.advance(task1)
                        continue

                except Exception as error:  # pylint: disable=broad-exception-caught
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
