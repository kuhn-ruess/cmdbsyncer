"""
Cisco DNA Syncer
"""
import requests
from requests.auth import HTTPBasicAuth

from application import app
from application.models.host import Host
from application.modules.debug import ColorCodes

class CiscoDNA():
    """
    Cisco DNA
    """


    def __init__(self, config):
        """
        Init
        """
        self.account_dict = config
        self.address = config['address']
        self.user = config['username']
        self.password = config['password']
        self.verify = not app.config.get('DISABLE_SSL_ERRORS')

#   .-- get_auth_token
    def get_auth_token(self):
        """
        Return Auth Token
        """
        print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Get Auth Token")
        url = f"{self.address}/dna/system/api/v1/auth/token"
        response = requests.request(
             "POST",
              url,
              auth=HTTPBasicAuth(self.user, self.password),
              verify=self.verify,
              timeout=30,
        )
        if response.status_code < 400:
            response_json = response.json()
            return response_json['Token']
        print(response.text)
        raise Exception("Connection Problem")


#.
#   .-- Command: get_interfaces
    def get_interfaces(self):
        """
          {'addresses': [{'address': {'ipAddress': {'address': '10.10.20.82'},
                                     'ipMask': {'address': '255.255.255.0'},
                                     'isInverseMask': False,
                                     'lazyLoadedEntities': None},
                         'lazyLoadedEntities': None,
                         'type': 'IPV4_PRIMARY'}],
          'adminStatus': 'UP',
          'className': 'VLANInterfaceExtended',
          'description': '',
          'deviceId': 'f0cb8464-1ce7-4afe-9c0d-a4b0cc5ee84c',
          'duplex': '',
          'id': '72ee5b47-0d6c-463f-a7b0-538714bd8ca0',
          'ifIndex': '54',
          'instanceTenantId': '5e8e896e4d4add00ca2b6487',
          'instanceUuid': '72ee5b47-0d6c-463f-a7b0-538714bd8ca0',
          'interfaceType': 'Virtual',
          'ipv4Address': '10.10.20.82',
          'ipv4Mask': '255.255.255.0',
          'isisSupport': 'false',
          'lastUpdated': None,
          'macAddress': '68:ca:e4:37:8d:d1',
          'managedComputeElement': None,
          'managedComputeElementUrl': None,
          'managedNetworkElement': {'id': 1159174,
                                    'longType': 'com.cisco.xmp.m...lity.ManagedNetworkElement',
                                    'type': 'ManagedNetworkElement',
                                    'url': '../../ManagedNetworkElement/1159174'},
          'managedNetworkElementUrl': '../../DeviceIf/-267/related/managedNetworkElement',
          'mappedPhysicalInterfaceId': None,
          'mappedPhysicalInterfaceName': None,
          'mediaType': None,
          'mtu': '1500',
          'name': None,
          'nativeVlanId': '',
          'networkdevice_id': 1150152,
          'ospfSupport': 'false',
          'pid': 'C9300-24U',
          'portMode': 'routed',
          'portName': 'Vlan835',
          'portType': 'Ethernet SVI',
          'poweroverethernet': 0,
          'serialNo': 'FCW2211G0MA',
          'series': 'Cisco Catalyst 9300 Series Switches',
          'speed': '1000000',
          'status': 'up',
          'vlanId': '835',
          'voiceVlan': ''
        """
        inventory_attributes = [
            'portName',
            'status',
            'adminStatus',
            'description',
            'mtu',
            'name',
            'interfaceType',
            'macAddress',
            'speed',
            'duplex',
            'portMode',
            'vlanId',
        ]
        token = self.get_auth_token()
        print(f"\n{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Start Sync")
        base_url = f"{self.address}/dna/intent/api/v1/interface/network-device/"
        headers = {"x-auth-token": token}

        #pylint: disable=no-member
        for db_host in Host.objects(available=True, source_account_id=self.account_id):
            print(f"{ColorCodes.HEADER}{db_host.hostname}{ColorCodes.ENDC}")
            url = base_url + db_host.sync_id
            #pylint: disable=missing-timeout
            response = requests.request("GET", url, headers=headers, verify=self.verify)
            response_json = response.json()['response']
            inventory = {}
            for interface in response_json:
                if_id = interface['id']
                for attribute in inventory_attributes:
                    inventory[f'cisco_dnainterface_{if_id}_{attribute}'] = interface[attribute]
            db_host.update_inventory('cisco_dnainterface_', inventory)
            db_host.save()


#.
#   .-- Command: get_hosts
    def get_hosts(self):
        """
        Get Host list
        {'apEthernetMacAddress': None,
          'apManagerInterfaceIp': '',
          'associatedWlcIp': '',
          'bootDateTime': '2021-10-31 01:54:27',
          'collectionInterval': 'Global Default',
          'collectionStatus': 'Managed',
          'description': 'Cisco IOS Software [Gibraltar], Catalyst L3 Switch Software '
                         '(CAT9K_IOSXE), Version 16.11.1c, RELEASE SOFTWARE (fc3) '
                         'Technical Support: http://www.cisco.com/techsupport '
                         'Copyright (c) 1986-2019 by Cisco Systems, Inc. Compiled Tue '
                         '18-Jun-19 21:21 by mcpre',
          'deviceSupportLevel': 'Supported',
          'errorCode': None,
          'errorDescription': None,
          'family': 'Switches and Hubs',
          'hostname': 'spine1.abc.inc',
          'id': 'f16955ae-c349-47e9-8e8f-9b62104ab604',
          'instanceTenantId': '5e8e896e4d4add00ca2b6487',
          'instanceUuid': 'f16955ae-c349-47e9-8e8f-9b62104ab604',
          'interfaceCount': '0',
          'inventoryStatusDetail': '<status><general code="SUCCESS"/></status>',
          'lastUpdateTime': 1665711027479,
          'lastUpdated': '2022-10-14 01:30:27',
          'lineCardCount': '0',
          'lineCardId': '',
          'location': None,
          'locationName': None,
          'macAddress': '70:1f:53:73:8d:00',
          'managedAtleastOnce': True,
          'managementIpAddress': '10.10.20.80',
          'managementState': 'Managed',
          'memorySize': 'NA',
          'platformId': 'C9300-48U',
          'reachabilityFailureReason': '',
          'reachabilityStatus': 'Reachable',
          'role': 'ACCESS',
          'roleSource': 'AUTO',
          'serialNumber': 'FOC2135Z00T',
          'series': 'Cisco Catalyst 9300 Series Switches',
          'snmpContact': '',
          'snmpLocation': '',
          'softwareType': 'IOS-XE',
          'softwareVersion': '16.11.1c',
          'tagCount': '0',
          'tunnelUdpPort': None,
          'type': 'Cisco Catalyst 9300 Switch',
          'upTime': '347 days, 23:36:23.24',
          'uptimeSeconds': 30086167,
          'waasDeviceMode': None}
        """
        inventory_attributes = [
            'id',
            'location',
            'platformId',
            'series',
            'serialNumber',
            'platformId',
            'location',
            'locationName',
            'role',
            'softwareType',
            'managementIpAddress',

        ]
        token = self.get_auth_token()
        print(f"\n{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Start Sync")
        url = f"{self.address}/dna/intent/api/v1/network-device?hostname=.*"
        headers = {"x-auth-token": token}
        #pylint: disable=missing-timeout
        response = requests.request("GET", url, headers=headers, verify=self.verify)
        response_json = response.json()['response']
        total = len(response_json)
        counter = 0
        for device in response_json:
            counter += 1
            process = 100.0 * counter / total
            hostname = device['hostname']
            print(f"{ColorCodes.HEADER}({process:.0f}%) {hostname}{ColorCodes.ENDC}")
            db_host = Host.get_host(hostname)
            inventory = {}
            inventory['manufacturer'] = "cisco"
            for attribute in inventory_attributes:
                inventory[f'cisco_dna_{attribute}'] = device[attribute]
            db_host.update_inventory('cisco_dna_', inventory)
            db_host.sync_id = device['id']
            db_host.set_import_seen()
            do_save = db_host.set_account(account_dict=self.account_dict)
            if do_save:
                db_host.save()
            print("  - Object owned by other Source, not saved")
