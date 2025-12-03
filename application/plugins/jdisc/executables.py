"""
JDISC Executables
"""
from .jdisc import JDisc

from syncerapi.v1.inventory import run_inventory


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

    def import_executables(self):
        """
        JDisc Executables Import
        """
        for labels in self.run_query()['devices']['findAll']:
            self.handle_object(labels, 'application')


    def inventorize(self):
        """
        JDisc Executables Inventorize
        """
        run_inventory(self.config, [(x['name'], x['operatingSystem']['installedExecutableFiles'])
                                      for x in self.run_query()['devices']['findAll'] if x['name']], 'executables')
