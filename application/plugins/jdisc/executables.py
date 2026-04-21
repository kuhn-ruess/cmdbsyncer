"""
JDISC Executables
"""
# pylint: disable=duplicate-code
from syncerapi.v1.inventory import run_inventory

from .jdisc import JDisc


class JdiscExecutables(JDisc):
    """
    JDISC Executables Import
    """

    def get_query(self):
        """
        Return Query for Executables
        """
        return """
            query test {
                devices {
                  findAll {
                    id
                    name
                    operatingSystem {
                     installedExecutableFiles {
                         executableFile {
                             binaryName
                                 name
                                 manufacturer
                                 version
                               }
                               installationPath
                     }
                    }
                  }
                }
            }
    """

    def _iter_device_executables(self):
        """Yield (device, executable_list) tuples, skipping devices
        without operatingSystem data instead of crashing."""
        for device in self.run_query()['devices']['findAll']:
            os_data = device.get('operatingSystem') or {}
            executables = os_data.get('installedExecutableFiles') or []
            yield device, executables

    def import_executables(self):
        """
        JDisc Executables Import
        """
        import_unnamed = self.config.get('import_unnamed_devices')
        for device, executables in self._iter_device_executables():
            device_key = device.get('name')
            if not device_key and import_unnamed and device.get('id') is not None:
                device_key = f"unnamed-{device['id']}"
            if not device_key:
                continue
            # Pass the list of executable wrappers to handle_object and
            # key each one by its owning device so identically named
            # binaries on different hosts stay distinct.
            self.handle_object(executables, 'executableFile', parent=('device', device_key))


    def inventorize(self):
        """
        JDisc Executables Inventorize
        """
        import_unnamed = self.config.get('import_unnamed_devices')
        entries = []
        for device, executables in self._iter_device_executables():
            hostname = device.get('name')
            if not hostname and import_unnamed and device.get('id') is not None:
                hostname = f"unnamed-{device['id']}"
            if not hostname:
                continue
            entries.append((hostname, executables))
        run_inventory(self.config, entries, 'executables')
