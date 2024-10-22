"""
Interface Syncronisation
"""
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host

from syncerapi.v1 import (
    cc,
)


class SyncInterfaces(SyncNetbox):
    """
    Interface Syncer
    """

    device_interface_cache = {}

#   .-- Get Interface Payload
    def get_interface_payload(self, device_id, if_attributes):
        """ Return Interface Payload
        """
        status_map = {
            'up' : True,
        }

        # @Todo: Detect Type:
        interface_type = "other"
        if if_attributes.get('interfaceType') == "Virtual":
            interface_type = 'virtual'


        duplex_modes = {
            'FullDuplex' : 'full',
            'HalfDuplex' : 'half',
        }
        duplex_mode = duplex_modes.get(if_attributes.get('duplex'), 'auto')

        access_modes = {
            'access': 'access',
            'trunk': 'tagged',
        }
        access_mode = access_modes.get(if_attributes.get('portMode'))

        interface_speed = int(if_attributes.get('speed',0))

        payload = {
          "device": device_id,
          #"module": 0,
          "name": if_attributes['portName'],
          #"label": "string",
          "type": interface_type,
          "enabled": status_map.get(if_attributes['adminStatus'].lower(), False),
          #"parent": 0,
          #"bridge": 0,
          #"lag": 0,
          "speed": interface_speed,
          "duplex": duplex_mode,
          #"wwn": "string",
          #"mgmt_only": true,
          "description": if_attributes.get('description', ""),
          #"rf_role": "ap",
          #"rf_channel": "2.4g-1-2412-22",
          #"poe_mode": "pd",
          #"poe_type": "type1-ieee802.3af",
          #"rf_channel_frequency": 0,
          #"rf_channel_width": 0,
          #"tx_power": 127,
          #"untagged_vlan": 0,
          #"tagged_vlans": [
          #  0
          #],
          #"mark_connected": true,
          #"cable": {
          #  "label": "string"
          #},
          #"wireless_link": 0,
          #"wireless_lans": [
          #  0
          #],
          #"vrf": 0,
          #"tags": [
          #  {
          #    "name": "string",
          #    "slug": "string",
          #    "color": "string"
          #  }
          #],
          #"custom_fields": {}
        }
        if if_attributes.get('macAddress'):
            payload['mac_address'] = if_attributes['macAddress'].upper()
        if access_mode:
            payload["mode"] =  access_mode
        if mtu := if_attributes.get('mtu'):
            payload["mtu"] = int(mtu)
        return payload
#.
#   .-- build interface_list
#    def get_interface_list_by_attributes(self, attributes):
#        """
#        Return List of Interfaces
#        """
#        interfaces = {}
#        for attribute, value in attributes.items():
#            # @TODO: Build more general approach
#            # Better RegEx Rewrites needed for that
#            if attribute.startswith('cisco_dnainterface'):
#                splitted = attribute.split('_')
#                interface_id = splitted[-2]
#                field_name = splitted[-1]
#                interfaces.setdefault(interface_id, {})
#                interfaces[interface_id][field_name] = value
#        return interfaces
#.

#   .-- Update Device Interfaces
    def update_interfaces(self, interfaces):
        """
        Update Interfaces based on Attributes
        """
        for interface_data in interfaces:
            if interface_data.get('ignore_interface'):
                continue
            device_id = interface_data['device']
            if device_id not in self.device_interface_cache:
                device_interfaces = {}
                url = f'dcim/interfaces?device_id={device_id}'
                for entry in self.request(url, "GET"):
                    # We need some rewrite here to match the payloads of the api
                    del entry['device']
                    entry['name'] = entry['display']
                    device_interfaces[entry['name']] = entry
            else:
                device_interfaces = self.device_interface_cache[device_id]

            url = 'dcim/interfaces/'
            #interfaces = self.get_interface_list_by_attributes(attributes)
            payload = self.get_interface_payload(device_id, interface_data)
            port_name = interface_data['portName']
            if port_name not in device_interfaces:
                self.progress(f"Create Interface {port_name}")
                create_response = self.request(url, "POST", payload)
            elif update_keys := self.need_update(device_interfaces[port_name], payload):
                update_payload = {}
                for key in update_keys:
                    update_payload[key] = payload[key]
                self.progrees(f"Update Interface {port_name} ({update_keys})")
                url = f'dcim/interfaces/{device_interfaces[port_name]["id"]}/'
                self.request(url, "PATCH", update_payload)

#.

    def sync_interfaces(self):
        """
        Iterarte over objects and sync them to Netbox
        """
        db_objects = Host.objects()
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.progress = progress.console.print
            task1 = progress.add_task("Updateing Interfaces for Devices", total=total)
            for db_host in db_objects:
                hostname = db_host.hostname

                all_attributes = self.get_host_attributes(db_host, 'netbox_hostattribute')
                if not all_attributes:
                    progress.advance(task1)
                    continue
                interfaces = self.get_host_data(db_host, all_attributes['all'])['interfaces']
                self.update_interfaces(interfaces)

                progress.advance(task1)
