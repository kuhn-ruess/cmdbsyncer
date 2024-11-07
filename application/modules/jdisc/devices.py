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
              hwVersion
              assetTag
              roles
              operatingSystem {
                osFamily
                osVersion
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
              operatingSystem {
                installedApplications {
                  source
                  application {
                    id
                    name
                    manufacturer
                    version
                  }
                  installationPath
                  installationDate
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
            host_obj.update_host(labels)
            do_save=host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
            else:
                print(f" {cc.WARNING} * {cc.ENDC} Managed by diffrent master")

    def device_inventorize(self):
        """
        JDisc Inventorize
        """
        run_inventory(self.config, self._inner_import())
