
"""
Ansible Inventory Modul
"""
from mongoengine.errors import DoesNotExist
from application.models.host import Host
from application.modules.plugin import Plugin

class SyncAnsible(Plugin):
    """
    Class for the Ansible Actions
    """

    def get_host_data(self, db_host, attributes):
        """
        Return extra Attributes based on
        rules which has existing attributes in condition
        """
        return self.actions.get_outcomes(db_host, attributes)

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
        for db_host in Host.objects(available=True):
            hostname = db_host.hostname

            attributes = self.get_host_attributes(db_host)
            if not attributes:
                continue
            extra_attributes = self.get_host_data(db_host, attributes['all'])
            if 'ignore_host' in extra_attributes:
                continue

            inventory = attributes['filtered']
            inventory.update(extra_attributes)

            data['_meta']['hostvars'][hostname] = inventory
            data['all']['hosts'].append(hostname)
        return data


    def get_host_inventory(self, hostname):
        """
        Get Inventory for single host
        """
        try:
            #pylint: disable=no-member
            db_host = Host.objects.get(hostname=hostname, available=True)
        except DoesNotExist:
            return False

        attributes = self.get_host_attributes(db_host)
        if not attributes:
            return False
        extra_attributes = self.get_host_data(db_host, attributes['all'])
        if 'ignore_host' in extra_attributes:
            return False

        inventory = attributes['filtered']
        inventory.update(extra_attributes)
        return inventory
