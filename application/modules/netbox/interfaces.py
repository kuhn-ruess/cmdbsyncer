"""
Interface Syncronisation
"""
from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host


class SyncInterfaces(SyncNetbox):
    """
    Interface Syncer
    """

#   .-- Get Interface Payload
    def get_interface_payload(self, host_id, if_attributes):
        """ Return Interface Payload
        """
        status_map = {
            'up' : True,
        }

        # @Todo: Detect Type:
        interface_type = "other"
        if if_attributes['interfaceType'] == "Virtual":
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
          "device": host_id,
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
          "description": if_attributes.get('description'),
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
        if if_attributes['macAddress']:
            payload['mac_address'] = if_attributes['macAddress'].upper()
        if access_mode:
            payload["mode"] =  access_mode
        if mtu := if_attributes.get('mtu'):
            payload["mtu"] = int(mtu)
        if self.print_debug:
            print(payload)
        return payload
#.
#   .-- build interface_list
    def get_interface_list_by_attributes(self, attributes):
        """
        Return List of Interfaces
        """
        interfaces = {}
        for attribute, value in attributes.items():
            # @TODO: Build more general approach
            # Better RegEx Rewrites needed for that
            if attribute.startswith('cisco_dnainterface'):
                splitted = attribute.split('_')
                interface_id = splitted[-2]
                field_name = splitted[-1]
                interfaces.setdefault(interface_id, {})
                interfaces[interface_id][field_name] = value
        return interfaces


#.
#   .-- Update Interfaces
    def update_interfaces(self, host_id, attributes):
        """
        Update Interfaces based on Attributes
        """
        url = f'dcim/interfaces?device_id={host_id}'
        device_interfaces = {}
        for entry in self.request(url, "GET"):
            # We need some rewrite here to match the payloads of the api
            del entry['device']
            entry['name'] = entry['display']
            device_interfaces[entry['name']] = entry

        url = 'dcim/interfaces/'
        interfaces = self.get_interface_list_by_attributes(attributes)
        for _interface, interface_data in interfaces.items():
            payload = self.get_interface_payload(host_id, interface_data)
            port_name = interface_data['portName']
            if port_name not in device_interfaces:
                print(f"{CC.OKBLUE} *{CC.ENDC} Create Interface {port_name}")
                create_response = self.request(url, "POST", payload)
                if self.print_debug:
                    print(f"Debug: Created Interface: {create_response}")
            elif update_keys := self.need_update(device_interfaces[port_name], payload):
                update_payload = {}
                for key in update_keys:
                    update_payload[key] = payload[key]
                print(f"{CC.OKGREEN} *{CC.ENDC} Update Interface {port_name} ({update_keys})")
                url = f'dcim/interfaces/{device_interfaces[port_name]["id"]}/'
                self.request(url, "PATCH", update_payload)

        print(f"{CC.OKGREEN} *{CC.ENDC} Check Sync of Interfaces")
#.
