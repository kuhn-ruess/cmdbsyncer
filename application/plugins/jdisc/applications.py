"""
JDISC Applications
"""
# pylint: disable=duplicate-code
from syncerapi.v1.inventory import run_inventory

from .jdisc import JDisc


class JdiscApplications(JDisc):
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

    def _iter_device_apps(self):
        """Yield (device, applications_list) tuples, skipping devices
        without operatingSystem data instead of crashing."""
        for device in self.run_query()['devices']['findAll']:
            os_data = device.get('operatingSystem') or {}
            applications = os_data.get('installedApplications') or []
            yield device, applications

    def import_applications(self):
        """
        JDisc Application Import
        """
        import_unnamed = self.config.get('import_unnamed_devices')
        for device, applications in self._iter_device_apps():
            device_key = device.get('name')
            if not device_key and import_unnamed and device.get('id') is not None:
                device_key = f"unnamed-{device['id']}"
            if not device_key:
                continue
            # Key each application by its owning device so identically
            # named software on different devices no longer collapses
            # onto the same Syncer object.
            self.handle_object(applications, 'application', parent=('device', device_key))


    def inventorize(self):
        """
        JDisc Application Inventorize
        """
        import_unnamed = self.config.get('import_unnamed_devices')
        entries = []
        for device, applications in self._iter_device_apps():
            hostname = device.get('name')
            if not hostname and import_unnamed and device.get('id') is not None:
                hostname = f"unnamed-{device['id']}"
            if not hostname:
                continue
            entries.append((hostname, applications))
        run_inventory(self.config, entries, 'applications')
