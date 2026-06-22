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

    @staticmethod
    def _core_attributes(vm):
        """
        Identifying fields present on every VM regardless of which command
        collected it, so the ``inventory_filter`` always has something to
        match against (e.g. ``power_state``, ``guest_os``).
        """
        return {
            "name": vm.name,
            "power_state": vm.runtime.powerState,
            "guest_os": vm.config.guestFullName if vm.config else None,
            # Readable ESXi host name instead of the internal MoRef
            "runtime_host": vm.runtime.host.summary.config.name if vm.runtime.host else None,
        }

    def get_vm_hardware(self, vm, _content):
        """Collect the VM's virtual-hardware inventory"""
        attributes = self._core_attributes(vm)
        attributes['resource_pool'] = vm.resourcePool.name if vm.resourcePool else "Default"

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
                "uuid": vm.config.uuid,
                "guest_id": vm.config.guestId,
                "annotation": vm.config.annotation,
            })
        if vm.runtime:
            attributes['boot_time'] = vm.runtime.bootTime
        if vm.network:
            attributes['networks'] = [{'name': network.name} for network in vm.network]
        if vm.datastore:
            attributes['datastores'] = [{'name': ds.info.name} for ds in vm.datastore]
        if vm.config and vm.config.hardware.device:
            attributes.update(self._collect_hardware_devices(vm))

        return attributes

    def get_vm_custom_attributes(self, vm, content):
        """Collect the VM's vCenter Custom Attributes (``vm.customValue``)"""
        attributes = self._core_attributes(vm)
        if vm.customValue:
            for custom_field in vm.customValue:
                field_key = custom_field.key
                field_name = next(
                    (f.name for f in content.customFieldsManager.field if f.key == field_key),
                    f"custom_{field_key}"
                )
                attributes[field_name] = custom_field.value
        return attributes

    def _collect(self, reader):
        """
        Run ``reader(vm, content)`` for every VM, normalise the result and
        keep only those matching the ``inventory_filter`` account setting
        (``key:value,key:value``; repeated key = OR, different keys = AND).
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
            attributes = {key: value if isinstance(value, (str, list)) else str(value)
                          for key, value in reader(vm, content).items()}
            if all(str(attributes.get(key)) in values
                   for key, values in inventory_filter.items()):
                data.append(attributes)
        return data


    def _write_custom_attributes(self, vm_handle, current_values, wanted):
        """
        Write each wanted custom attribute that differs from the VM's current
        value (skipped on dry_run) and return the list of applied changes.
        With ``--debug`` every attribute is reported with the reason it is
        written or skipped.
        """
        changes = []
        for attr_name, attr_value in wanted.items():
            # Only write when the value actually differs from what is already
            # on the VM. ``get`` returns None for attributes not yet set, which
            # never equals a rendered string, so genuinely new values are written.
            current = current_values.get(attr_name)
            if current == attr_value:
                if self.debug:
                    self.console(f"   = {attr_name}: unchanged ({attr_value!r}), skipped")
                continue
            reason = "not set on VM yet" if current is None else f"differs from {current!r}"
            changes.append(f"{attr_name}: {current} to {attr_value}")
            if self.debug:
                verb = "would write" if self.dry_run else "writing"
                self.console(f"   * {attr_name}: {verb} {attr_value!r} — {reason}")
            if not self.dry_run:
                vm_handle.SetCustomValue(key=attr_name, value=attr_value)
        return changes

    def export_attributes(self):
        """
        Export Custom Attributes
        """
        self.connect()
        current_attributes = {x['name']:x for x in self._collect(self.get_vm_custom_attributes)}

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
                    if not (vm_host_data := current_attributes.get(hostname)):
                        logger.debug(" Not found in VMware Data")
                        progress.advance(task1)
                        continue
                    changes = self._write_custom_attributes(
                        current_vms[hostname], vm_host_data, custom_rules['attributes'])
                    if changes and self.dry_run:
                        self.console(f"   [dry-run] would update: {changes}")
                    logger.debug(" Updated: %s", changes)

                except Exception as error:  # pylint: disable=broad-exception-caught
                    if self.debug:
                        raise
                    self.log_details.append((f'export_error {hostname}', str(error)))
                    self.console(f" Error in process: {error}")
                progress.advance(task1)


    def inventorize_attributes(self):
        """
        Inventorize the VMs' vCenter Custom Attributes
        """
        self.connect()
        data = self._collect(self.get_vm_custom_attributes)
        if self.dry_run:
            logger.info("Dry-run: would inventorize %s VMs, nothing written", len(data))
            return
        run_inventory(self.config, [(x['name'], x) for x in data])

    def inventorize_hardware(self):
        """
        Inventorize the VMs' virtual hardware under the ``_hardware`` sub-key
        """
        self.connect()
        data = self._collect(self.get_vm_hardware)
        if self.dry_run:
            logger.info("Dry-run: would inventorize %s VMs, nothing written", len(data))
            return
        run_inventory(self.config, [(x['name'], x) for x in data], sub_key='hardware')
