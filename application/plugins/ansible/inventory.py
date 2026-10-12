
"""
Ansible Inventory Modul
"""
# pylint: disable=duplicate-code
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from mongoengine.errors import DoesNotExist
from application.models.host import Host
from application.modules.plugin import Plugin
from application import logger

class AnsibleInventory(Plugin):
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
            'cmk_create_host',
            'cmk_register_bakery',
            'cmk_register_central_bakery',
            'cmk_install_agent',
            'cmk_discover',
            'dont_bypass',
        ]
        # If not at leas one of the attributes is True,
        # we have to ignore the host
        for check in checks:
            if attributes1.get(check.lower(), "false").lower() == "true":
                return False
            if attributes2.get(check.lower(), "false").lower() == "true":
                return False
        return True


    def get_host_data(self, db_host, attributes):
        """
        Return extra Attributes based on
        rules which has existing attributes in condition
        """
        if db_host.cache.get('ansible',{}).get('outcomes'):
            return db_host.cache['ansible']['outcomes']
        outcomes = self.actions.get_outcomes(db_host, attributes)  # pylint: disable=no-member
        db_host.cache.setdefault('ansible', {})
        db_host.cache['ansible']['outcomes'] = outcomes
        db_host.save()
        return outcomes

    def _convert_string_booleans(self, data):
        """
        Convert string "true"/"false" values to Python booleans recursively
        """
        if isinstance(data, dict):
            return {k: self._convert_string_booleans(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._convert_string_booleans(item) for item in data]
        if isinstance(data, str) and data.lower() in ['true', 'false']:
            return data.lower() == 'true'
        return data

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
            # Match the single-host lookup below: only return hosts whose
            # lifecycle state is 'active' so --list and --host agree on
            # which hostnames exist in this source.
            query = Host.get_export_hosts()
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

                #if self.bypass_host(attributes['all'], extra_attributes):
                #    if show_status:
                #        progress.advance(task1)
                #    continue

                inventory = attributes['filtered']
                inventory.update(extra_attributes)
                inventory = self._convert_string_booleans(inventory)

                data['_meta']['hostvars'][hostname] = inventory
                data['all']['hosts'].append(hostname)
                if show_status:
                    progress.advance(task1)
        for hostname, inventory in self.list_row_inventories():
            data['_meta']['hostvars'][hostname] = inventory
            data['all']['hosts'].append(hostname)
        return data

    def list_row_inventories(self):
        """
        ``(hostname, variables)`` of every row of a list rule: one more
        inventory host, named by the row's ``hostname`` (or ``name``)
        column, with the row's columns and the rule's variables. Kept off
        the terminal: the inventory is read from stdout.
        """
        for row in self.actions.list_rows():  # pylint: disable=no-member
            if not row.name or 'ignore_host' in row.outcomes:
                continue
            yield row.name, self._convert_string_booleans(
                {**row.attributes['filtered'], **row.outcomes})
        for message in self.actions.list_errors:  # pylint: disable=no-member
            logger.error(message)


    def get_host_inventory(self, hostname):
        """
        Get Inventory for single host
        """
        try:
            db_host = Host.get_export_hosts().get(hostname=hostname)
        except DoesNotExist:
            return dict(self.list_row_inventories()).get(hostname, False)

        attributes = self.get_attributes(db_host, 'ansible')
        if not attributes:
            return False
        extra_attributes = self.get_host_data(db_host, attributes['all'])
        if 'ignore_host' in extra_attributes:
            return False

        inventory = attributes['filtered']
        inventory.update(extra_attributes)
        inventory = self._convert_string_booleans(inventory)
        return inventory
