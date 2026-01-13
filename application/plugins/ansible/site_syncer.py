
"""
Ansible Checkmk Modul
"""
import jinja2
from mongoengine.errors import DoesNotExist
from application.plugins.checkmk.models import CheckmkSite
from application.modules.plugin import Plugin

class SyncSites(Plugin):
    """
    Class for the Checkmk Site Actions
    """


    def get_site_data(self, site):
        """
        Return Inventory for site
        """
        inventory = {}
        if site.settings_master.server_user:
            inventory['ansible_user'] =  site.settings_master.server_user


        file_template = jinja2.Template(site.settings_master.cmk_version_filename,)
        filename = file_template.render(CMK_VERSION=site.settings_master.cmk_version,
                                        CMK_EDITION=site.settings_master.cmk_edition)

        inventory.update({
            'cmk_site': site.name,
            'inital_password': site.settings_master.inital_password,
            'cmk_edition': site.settings_master.cmk_edition,
            'cmk_version': site.settings_master.cmk_version,
            'cmk_version_filename': filename,
            'subscription_username': site.settings_master.subscription_username,
            'subscription_password': site.settings_master.subscription_password,
            'webserver_certificate': site.settings_master.webserver_certificate,
            'webserver_private_certificate': site.settings_master.webserver_certificate_private_key,
            'webserver_intermediate_certificate': site.settings_master.webserver_certificate_intermediate,
        })
        for custom_var in site.custom_ansible_variables:
            inventory[custom_var.variable_name] = custom_var.variable_value
        return inventory

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
