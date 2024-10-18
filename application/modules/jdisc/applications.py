"""
JDISC Applications
"""
from application.modules.jdisc.jdisc import JDisc

from syncerapi.v1 import (
    Host,
    cc,
)

from application.helpers.inventory import inventorize_host


class JdiscApplications(JDisc):
    """
    JDISC Device Import
    """

    def get_query(self):
        """
        Return Query for Devices
        """
        return """
            devices {
              findAll {
                id
                name
                operatingSystem {
                  installedApplications {
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
    """

    def import_applications(self):
        """
        JDisc Import
        """
        already_found = []
        for labels in self.run_query()['devices']:
            applications =  labels['operatingSystem']['installedApplications']
            self.handle_object(applications, 'application')
