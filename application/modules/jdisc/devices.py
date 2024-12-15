"""
Jdisc Device Import
"""

from application.modules.jdisc.jdisc import JDisc

from syncerapi.v1.inventory import run_inventory
from syncerapi.v1 import (
    Host,
    cc,
)

class JdiscDevices(JDisc):
    """
    JDISC Device Import
    """


    def fix_networkinterfaces(self, labels):
        """
        Flat networkInterface
        """
        ip4_interfaces = []
        ip6_interfaces = []
        if "networkinterfaces" in labels:
            for interface in labels['networkinterfaces']:
                for config in interface['ip4Transports']:
                    ip4_interfaces.append(config)
                for config in interface['ip6Transports']:
                    ip6_interfaces.append(config)
            del labels['networkinterfaces']
            labels['network_ipv4_interfaces'] = ip4_interfaces
            labels['network_ipv6_interfaces'] = ip6_interfaces
        return labels



    def get_query(self):
        """
        Return Query for Devices
        """

        return """
        query test {
           devices {
            findAll {
              id
              name
              computername
              type
              manufacturer
              serialNumber
              logicalSerialNumber
              hwVersion
              assetTag
              roles
              model
              operatingSystem {
                osFamily
                osVersion
                patchLevel
                rawVersion
                description
                kernelVersion
              }
              partNumber
              systemBoard {
                id
              }
              mainIPAddress
              mainIP4Transport {
                hostnames
                ipAddress
                subnetMask
                networkInterface {
                  physicalAddress
                  type
                  index
                  extendedDescription
                  operationalStatus
                  administrativeStatus
                  description
                  speed
                  duplexMode
                  mtu
                }
                network {
                  name
                  nameManuallyConfigured
                  networkBaseAddress
                  subnetMask
                }
              }
              mainIP6Transport {
                ipAddress
                configuredPrefixLength
                network {
                  name
                  nameManuallyConfigured
                  prefixLength
                  networkBaseAddress
                }
              }
            networkInterfaces {
              ip4Transports {
                hostnames
                ipAddress
                hostnames
                ipAddress
                subnetMask
                networkInterface {
                  physicalAddress
                  type
                  index
                  duplexMode
                  extendedDescription
                  operationalStatus
                  speed
                  mtu
                  administrativeStatus
                  description
                }
                network {
                  name
                  nameManuallyConfigured
                  networkBaseAddress
                  subnetMask
                }
              }
              ip6Transports {
                hostnames
                ipAddress
                hostnames
                ipAddress
                configuredPrefixLength
                networkInterface {
                  physicalAddress
                  type
                  index
                  duplexMode
                  extendedDescription
                  operationalStatus
                  speed
                  mtu
                  administrativeStatus
                  description
                }
                network {
                  name
                  nameManuallyConfigured
                  networkBaseAddress
                  prefixLength
                }
              }
            }
          }
        }
       }
    """

    def import_devices(self):
        """
        JDisc Import
        """
        for labels in self.run_query()['devices']['findAll']:
            if 'name' not in labels:
                continue
            hostname = labels['name']
            if 'rewrite_hostname' in self.config and self.config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname,
                                                 self.config['rewrite_hostname'], labels)
            print(f" {cc.OKGREEN}* {cc.ENDC} Check {hostname}")
            del labels['name']
            host_obj = Host.get_host(hostname)
            labels = self.fix_networkinterfaces(labels)
            host_obj.update_host(labels)
            do_save=host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
            else:
                print(f" {cc.WARNING} * {cc.ENDC} Managed by diffrent master")

    def inventorize(self):
        """
        JDisc Application Inventorize
        """
        run_inventory(self.config, [(x['name'], x) for x in \
                            self.run_query()['devices']['findAll'] if x['name']])
