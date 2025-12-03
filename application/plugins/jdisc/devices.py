"""
Jdisc Device Import
"""

from .jdisc import JDisc

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
            except Exception as error:
                if self.debug:
                    raise
                self.log_details.append((f'export_error {hostname}', str(error)))
                print(f" Error in process: {error}")


    def inventorize(self):
        """
        JDisc Application Inventorize
        """
        run_inventory(self.config, [(x['name'], x) for x in \
                            self.run_query()['devices']['findAll'] if x['name']])
