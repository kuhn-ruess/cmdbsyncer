"""
Import Jira Data
"""
from application import logger
from application.models.host import Host
from application.modules.debug import ColorCodes
from application.modules.plugin import Plugin


class JiraOnPrem(Plugin):
    """
    Classic on-premise Jira Insight / Assets importer.

    Goes through the shared Plugin HTTP path so account-level
    verify_cert, ca_cert_chain and ca_root_cert are honored like in
    every other plugin, and pages through /environments and /servers
    so large inventories are imported completely.
    """

    name = "Jira OnPrem: Import Hosts"
    source = "jira_onprem_import"

    def _paginated_get(self, url, page_size):
        """Yield every item from a paginated Jira endpoint."""
        start_at = 0
        while True:
            params = {'pageSize': page_size, 'startAt': start_at}
            response = self.inner_request(
                method='GET', url=url,
                params=params,
                auth=(self.config['username'], self.config['password']),
            )
            body = response.json()
            items = body.get('data', [])
            if not items:
                return
            yield from items
            # Jira paginated endpoints use isLast/nextPage/total; cover
            # both the total-count form and the isLast flag.
            if body.get('isLast'):
                return
            total = body.get('total')
            start_at += len(items)
            if total is not None and start_at >= total:
                return
            if len(items) < page_size:
                return

    def _collect_meta(self):
        """Load meta tables (environments etc.) that hosts reference by id."""
        page_size = self.config['page_size']
        meta = {}
        meta_config = [
            {
                'name': 'environment',
                'url': f"{self.config['address']}/environments",
                'attribute': 'identifier',
            }
        ]
        for what in meta_config:
            name = what['name']
            print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Request: Read {name} Data")
            meta[name] = {}
            for entry in self._paginated_get(what['url'], page_size):
                meta[name][entry['key']] = entry[what['attribute']]
        return meta, meta_config

    # pylint: disable-next=too-many-locals
    def import_hosts(self):
        """Import hosts from the classic Jira Insight /servers endpoint."""
        page_size = self.config['page_size']
        meta, meta_config = self._collect_meta()
        meta_names = [x['name'] for x in meta_config]

        url = f"{self.config['address']}/servers"
        print(f"{ColorCodes.OKGREEN} -- {ColorCodes.ENDC}Request: Read all Hosts")

        all_data = list(self._paginated_get(url, page_size))
        total = len(all_data)
        for counter, host in enumerate(all_data, start=1):
            logger.debug('Host Data: %s', host)
            hostname = host['name']
            process = 100.0 * counter / total if total else 0
            print(f"{ColorCodes.OKGREEN}({process:.0f}%){ColorCodes.ENDC} {hostname}")
            host_obj = Host.get_host(hostname)
            host_obj.raw = str(host)
            del host['name']

            attributes = {}
            for attr, attr_value in host.items():
                if attr in meta_names and isinstance(attr_value, dict):
                    attributes[attr] = meta[attr].get(attr_value.get('id'))
                elif isinstance(attr_value, dict):
                    attributes[attr] = attr_value.get('value')
                elif isinstance(attr_value, list):
                    for idx, value in enumerate(attr_value):
                        if isinstance(value, dict):
                            attributes[f'{attr}_{idx}'] = value.get('value')
            host_obj.update_host(attributes)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()


def import_jira(account):
    """
    Import hosts from a classic on-prem Jira Insight / Assets instance.
    """
    jira = JiraOnPrem(account)
    jira.import_hosts()
