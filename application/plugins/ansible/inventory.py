
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
    # Cache slot prefix of the attribute set. Set per project by the
    # provider, so two projects never serve each other's cached values.
    cache_key = "ansible"


    def get_host_data(self, db_host, attributes, persist_cache=True):
        """
        Return extra Attributes based on
        rules which has existing attributes in condition
        """
        return self.actions.get_outcomes(  # pylint: disable=no-member
            db_host, attributes, persist_cache=persist_cache)

    def get_host_vars(self, db_host):
        """
        The inventory variables of one host, False if a rule drops it.

        The rule engines collect their cache writes and the host is saved
        once at the end, instead of once per engine.
        """
        attributes = self.get_attributes(db_host, self.cache_key, persist_cache=False)
        extra_attributes = {}
        if attributes:
            extra_attributes = self.get_host_data(db_host, attributes['all'],
                                                  persist_cache=False)
        self.flush_host_cache(db_host)
        if not attributes or 'ignore_host' in extra_attributes:
            return False
        # A new dict: the filtered set is the cached one of the host
        return self._convert_string_booleans(
            {**attributes['filtered'], **extra_attributes})

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
            # no_cache(): every host is needed once, the queryset must not
            # keep all of them in memory until the end of the run
            for db_host in query.no_cache():
                inventory = self.get_host_vars(db_host)
                if inventory:
                    data['_meta']['hostvars'][db_host.hostname] = inventory
                    data['all']['hosts'].append(db_host.hostname)
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

        return self.get_host_vars(db_host)
