"""
JDISC Applications
"""
from .jdisc import JDisc

from syncerapi.v1.inventory import run_inventory


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

    def import_applications(self):
        """
        JDisc Application Import
        """
        for labels in self.run_query()['devices']['findAll']:
            applications =  labels['operatingSystem']['installedApplications']
            self.handle_object(applications, 'application')


    def inventorize(self):
        """
        JDisc Application Inventorize
        """
        run_inventory(self.config, [(x['name'], x['operatingSystem']['installedApplications'])
                                      for x in self.run_query()['devices']['findAll'] if x['name']], 'applications')
