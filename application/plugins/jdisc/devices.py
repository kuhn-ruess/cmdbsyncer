"""
Jdisc Device Import
"""

from syncerapi.v1.inventory import run_inventory
from syncerapi.v1 import (
    cc,
)
from application.helpers.import_hostnames import get_import_hosts, update_import_host

from .jdisc import JDisc

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
              bios {
                version
              }
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
              ip4Transports {
                hostnames
                ipAddress
                hostnames
                ipAddress
                subnetMask
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
            try:
                if 'name' not in labels:
                    continue
                hostname = labels['name']

                if not hostname and self.config.get('import_unnamed_devices'):
                    hostname = f'unnamed-{labels["serialNumber"]}'
                elif not hostname:
                    self.log_details.append(('unnamed_device_skipped', f'{labels["serialNumber"]}'))
                    continue
                hosts = get_import_hosts(hostname, self.config, labels)
                del labels['name']
                for hostname, host_obj in hosts:
                    print(f" {cc.OKGREEN}* {cc.ENDC} Check {hostname}")
                    if not update_import_host(host_obj, labels, self.config):
                        print(f" {cc.WARNING} * {cc.ENDC} Managed by diffrent master")
            except Exception as error:  # pylint: disable=broad-exception-caught
                if self.debug:
                    raise
                self.log_details.append((f'export_error {hostname}', str(error)))
                print(f" Error in process: {error}")


    def inventorize(self):
        """
        JDisc Application Inventorize
        """
        import_unnamed = self.config.get('import_unnamed_devices')
        entries = []
        for dev in self.run_query()['devices']['findAll']:
            hostname = dev.get('name')
            if not hostname and import_unnamed and dev.get('serialNumber'):
                # Mirror import_devices so nameless devices that get
                # imported as unnamed-<serial> also receive inventory.
                hostname = f"unnamed-{dev['serialNumber']}"
            if not hostname:
                continue
            # run_inventory applies rewrite_hostname, the same way the
            # import does
            entries.append((hostname, dev))
        run_inventory(self.config, entries)
