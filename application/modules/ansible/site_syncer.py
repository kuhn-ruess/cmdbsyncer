
"""
Ansible Inventory Modul
"""
from mongoengine.errors import DoesNotExist
from application.modules.checkmk.models import CheckmkSite
from application.modules.plugin import Plugin

class SyncSites(Plugin):
    """
    Class for the Checkmk Site Actions
    """


    def get_site_data(self, site):
        """
        Return Inventory for site
        """
        return {
            'ansible_user': site.settings_master.server_user,
            'cmk_site': site.name,
            'cmk_edition': site.settings_master.cmk_edition,
            'cmk_version': site.settings_master.cmk_version,
            'cmk_version_filename': site.settings_master.cmk_version_filename,
            'subscription_username': site.settings_master.subscription_username,
            'subscription_password': site.settings_master.subscription_password,
        }

    def get_full_inventory(self):
        """
        Get Full Inventory Information for Ansible
        """
        data = {
            '_meta': {
                'hostvars' : {}
            },
            'all': {
                'hosts' : []
            },
        }
        #pylint: disable=no-member
        for site in CheckmkSite.objects(enabled=True):
            hostname = site.server_address
            data['_meta']['hostvars'][hostname] = self.get_site_data(site)
            data['all']['hosts'].append(hostname)
        return data


    def get_host_inventory(self, hostname):
        """
        Get Inventory for single host
        """
        try:
            #pylint: disable=no-member
            site = CheckmkSite.objects.get(server_address=hostname, available=True)
        except DoesNotExist:
            return False
        return self.get_site_data(site)
