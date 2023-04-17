
"""
Ansible Inventory Modul
"""
from mongoengine.errors import DoesNotExist
from application import app
from application.models.host import Host
from application.modules.plugin import Plugin

class SyncAnsible(Plugin):
    """
    Class for the Ansible Actions
    """


    def bypass_host(self, attributes1, attributes2):
        """
        Check if we should ignore a host
        """
        checks = [
            ('cmk_register_tls', "False"),
            ('cmk_register_bakery', "False"),
            ('cmk_install_agent', "False"),
            ('cmk_do_discover', "False"),
        ]
        for check, target in checks:
            if attributes1.get(check, "False") != target:
                return False
            if attributes2.get(check, "False") != target:
                return False
        return True


    def get_host_data(self, db_host, attributes):
        """
        Return extra Attributes based on
        rules which has existing attributes in condition
        """
        if db_host.cache.get('ansible',{}).get('outcomes'):
            return db_host.cache['ansible']['outcomes']
        outcomes = self.actions.get_outcomes(db_host, attributes)
        db_host.cache.setdefault('ansible', {})
        db_host.cache['ansible']['outcomes'] = outcomes
        db_host.save()
        return outcomes


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

            attributes = self.get_host_attributes(db_host, 'ansible')
            if not attributes:
                continue
            extra_attributes = self.get_host_data(db_host, attributes['all'])
            if 'ignore_host' in extra_attributes:
                continue

            if self.bypass_host(attributes['all'], extra_attributes):
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

        attributes = self.get_host_attributes(db_host, 'ansible')
        if not attributes:
            return False
        extra_attributes = self.get_host_data(db_host, attributes['all'])
        if 'ignore_host' in extra_attributes:
            return False

        inventory = attributes['filtered']
        inventory.update(extra_attributes)
        return inventory
