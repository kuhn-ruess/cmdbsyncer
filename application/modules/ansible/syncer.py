
"""
Ansible Inventory Modul
"""
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from mongoengine.errors import DoesNotExist
from application.models.host import Host
from application.modules.plugin import Plugin

class SyncAnsible(Plugin):
    """
    Class for the Ansible Actions
    """


    name = "Ansible"
    source = "ansible_jobs"


    def bypass_host(self, attributes1, attributes2):
        """
        Check if we should ignore a host
        """
        checks = [
            'cmk_register_tls',
            'cmk_register_bakery',
            'cmk_register_central_bakery',
            'cmk_install_agent',
            'cmk_discover',
        ]
        # If not at leas one of the attributes is True,
        # we have to ignore the host
        for check in checks:
            if attributes1.get(check.lower(), "false") == "true":
                return False
            if attributes2.get(check.lower(), "false") == "true":
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


    def get_full_inventory(self, show_status=False):
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
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            #pylint: disable=no-member
            query = Host.objects()
            if show_status:
                task1 = progress.add_task("Calculating Variables", total=query.count())
            for db_host in query:
                hostname = db_host.hostname

                attributes = self.get_attributes(db_host, 'ansible')
                if not attributes:
                    if show_status:
                        progress.advance(task1)
                    continue
                extra_attributes = self.get_host_data(db_host, attributes['all'])
                if 'ignore_host' in extra_attributes:
                    if show_status:
                        progress.advance(task1)
                    continue

                if self.bypass_host(attributes['all'], extra_attributes):
                    if show_status:
                        progress.advance(task1)
                    continue

                inventory = attributes['filtered']
                inventory.update(extra_attributes)

                data['_meta']['hostvars'][hostname] = inventory
                data['all']['hosts'].append(hostname)
                if show_status:
                    progress.advance(task1)
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

        attributes = self.get_attributes(db_host, 'ansible')
        if not attributes:
            return False
        extra_attributes = self.get_host_data(db_host, attributes['all'])
        if 'ignore_host' in extra_attributes:
            return False

        inventory = attributes['filtered']
        inventory.update(extra_attributes)
        return inventory
