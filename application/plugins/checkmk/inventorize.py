"""
Checkmk Inventorize
"""
# pylint: disable=too-many-locals,too-many-branches,too-many-nested-blocks,duplicate-code
import datetime
import hashlib
import json
import multiprocessing

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application.models.host import Host, app
from application.models.host_inventory_tree import (
    HostInventoryTree,
    HostInventoryTreePath,
)
from application.plugins.checkmk.models import (
   CheckmkInventorizeAttributes
)
from application.plugins.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes

# Source identifier for the HW/SW tree side-document. Kept in lockstep
# with the Host.inventory key prefix so a curated subset and its full
# tree share the same name.
HW_SW_TREE_SOURCE = "cmk_hw_sw_inv"


#@TODO Refactor into class with small methods

class InventorizeHosts(CMK2):  # pylint: disable=too-many-instance-attributes
    """
    Host Inventorize in Checkmk
    """

    name = "Checkmk Inventory run"
    source = "cmk_inventorize"

    def add_host(self, host):
        """
        Register a host name once. `found_hosts` is a set so repeated calls
        across the service / label / attribute collectors are O(1) instead
        of a linear scan per hit (matters at 10k+ services).
        """
        self.found_hosts.add(host)

    def __init__(self, account):
        """Init"""

        super().__init__(account)

        # Per-instance run state. Previously these were class-level and
        # retained data across accounts / repeated runs, so later runs
        # wrote back stale hosts and inventory blocks to the DB.
        self.fields = {}
        self.found_hosts = set()
        self.status_inventory = {}
        self.hw_sw_inventory = {}
        self.service_label_inventory = {}
        self.config_inventory = {}
        self.label_inventory = {}

        for rule in CheckmkInventorizeAttributes.objects():
            self.fields.setdefault(rule.attribute_source, [])
            field_list = [x.strip() for x in rule.attribute_names.split(',')]
            self.fields[rule.attribute_source] += field_list


    def get_hw_sw_inventory_data(self, hostname):
        """
        Fetch and flatten HW/SW inventory for a single host.

        Returns ``(hostname, filtered_subset)`` — only the small curated
        dict that gets promoted onto ``Host.inventory`` for the rule
        engine. The full flat tree is persisted to ``HostInventoryTree``
        directly from the worker so it never crosses the multiprocessing
        IPC boundary; shipping a 100-500 KB blob per host through the
        result pipe was a runtime catastrophe at scale.
        """
        url = f"host_inv_api.py?host={hostname}&output_format=json"
        dict_inventory = self.request(url, method="GET", api_version="/")[0]['result'][hostname]
        if not dict_inventory:
            return hostname, None

        def flatten_inventory(data, path=""):
            result = {}

            if data.get('Attributes') and data['Attributes'].get('Pairs'):
                for key, value in data['Attributes']['Pairs'].items():
                    flat_key = f"{path}.{key}" if path else key
                    result[flat_key] = value

            if data.get('Table') and data['Table'].get('Rows'):
                rows = data['Table']['Rows']
                result[path] = rows

            if data.get('Nodes'):
                for node_name, node_data in data['Nodes'].items():
                    new_path = f"{path}.{node_name}" if path else node_name
                    result.update(flatten_inventory(node_data, new_path))

            return result

        flat_inventory = flatten_inventory(dict_inventory)

        return_data = {}
        for needed_field in self.fields['cmk_inventory']:
            # Now Always a Wildcard
            if needed_field.endswith('*'):
                needed_field = needed_field[:-1]

            for key, data in flat_inventory.items():
                friendly_name = key.replace('.', '_')
                if key.startswith(needed_field):
                    return_data[friendly_name] = data

        # Side-doc write happens here, in-worker, so only the small
        # curated subset travels back to the parent process.
        self._save_inventory_tree(hostname, flat_inventory)

        return hostname, return_data


    def get_hw_sw_inventory(self):
        """ Query HW/SW Inventory"""
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting possible Hosts for HW/SW")
        url = "domain-types/service/collections/all"

        params={
            "query":
               '{ "op": "=", "left": "description", "right": "Check_MK HW/SW Inventory"}',
            "columns": ['host_name']
        }

        api_response = self.request(url, params=params, method="GET")
        response = api_response[0]['value']
        total = len(response)
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Requesting HW/SW Inventory Data from Checkmk", total=total)
            with multiprocessing.Pool() as pool:
                tasks = []
                for host_resp in response:
                    hostname = host_resp['extensions']['host_name']
                    self.add_host(hostname)
                    task = pool.apply_async(self.get_hw_sw_inventory_data, args=(hostname,))
                    tasks.append(task)

                for task in tasks:
                    try:
                        hostname, data = task.get(timeout=app.config['PROCESS_TIMEOUT'])
                    except multiprocessing.TimeoutError:
                        progress.console.print("- ERROR: Timeout for a object")
                    except Exception as error:  # pylint: disable=broad-exception-caught
                        if self.debug:
                            raise
                        progress.console.print(f"- ERROR: Timeout error for object ({error})")
                    else:
                        progress.advance(task1)
                        if data is not None:
                            self.hw_sw_inventory[hostname] = data
                pool.close()
                pool.join()

    def get_cmk_services(self):
        """ Get CMK Services"""
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting Service Data")
        url = "domain-types/service/collections/all"

        columns = ['host_name', 'description', 'state', 'plugin_output', 'host_labels']

        expr = []
        expr.append({"op": "=", "left": "description", "right": "Check_MK"})
        for field in self.fields.get('cmk_services', []):
            expr.append({"op": "=", "left": "description", "right": field})

        query = {
            "op": "or",
            "expr": expr,
        }
        params={
            "query": str(json.dumps(query)),
            "columns": columns
        }

        api_response = self.request(url, params=params, method="GET")
        for service in api_response[0]['value']:
            hostname = service['extensions']['host_name']
            self.add_host(hostname)
            service_description = service['extensions']['description'].lower().replace(' ', '_')
            if not 'state' in service['extensions']:
                continue
            service_state = service['extensions']['state']
            service_output = service['extensions']['plugin_output']
            labels = service['extensions']['host_labels']
            self.status_inventory.setdefault(hostname, {})
            self.label_inventory.setdefault(hostname, {})
            for label, label_value in labels.items():
                self.label_inventory[hostname][label] = label_value

            self.status_inventory[hostname][f"{service_description}_state"] = service_state
            self.status_inventory[hostname][f"{service_description}_output"] = service_output

    def get_service_labels(self):
        """
        Get Service Labels
        """
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting Service Labels")
        columns = ['host_name','label_names', 'label_values']
        expr = []
        for field in self.fields['cmk_service_labels']:
            expr.append({"op": "~", "left": "description", "right": field})
        query = {
            "op": "or",
            "expr": expr,
        }
        params={
            "query": str(json.dumps(query)),
            "columns": columns
        }
        url = "domain-types/service/collections/all"
        api_response = self.request(url, params=params, method="GET")
        for service in api_response[0]['value']:
            names = service['extensions']['label_names']
            values = service['extensions']['label_values']
            if not names:
                continue
            hostname = service['extensions']['host_name']
            self.add_host(hostname)
            self.service_label_inventory.setdefault(hostname, {})
            for name, value in zip(names, values):
                self.service_label_inventory[hostname][name] = value


    def get_attr_labels(self):
        """ Gett Attribute and Labels """
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting Config Data")

        if app.config['CMK_GET_HOST_BY_FOLDER']:
            self._fetch_checkmk_host_by_folder(extra_params="?effective_attributes=true")
        else:
            self.fetch_all_checkmk_hosts(extra_params="?effective_attributes=true")

        for hostname, host in self.checkmk_hosts.items():
            self.add_host(hostname)
            attributes = host['extensions']
            if not attributes:
                continue
            if attributes['effective_attributes']:
                attributes.update(attributes['effective_attributes'])
                del attributes['effective_attributes']

            host_inventory = {}

            if self.fields.get('cmk_attributes'):
                for attribute_key, attribute_value in attributes.items():
                    if attribute_key in self.fields['cmk_attributes']:
                        host_inventory[attribute_key] = attribute_value
                for search in self.fields['cmk_attributes']:
                    if search.endswith('*'):
                        needle = search[:-1]
                        for attribute_key, attribute_value in attributes.items():
                            if attribute_key.startswith(needle):
                                host_inventory[attribute_key] = attribute_value

            if self.fields.get('cmk_labels'):
                labels = self.label_inventory.get(hostname, {})
                labels.update(attributes.get('labels', {}))
                # Checkmk labels such as `piggyback_source_<hostname>` embed a
                # FQDN in the label name; MongoDB rejects dots in field names,
                # so flatten them the same way as in the HW/SW inventory path.
                for label_key, label_value in labels.items():
                    if label_key in self.fields['cmk_labels']:
                        label_key = label_key.replace('cmk/', '').replace('.', '_')
                        host_inventory['label_'+label_key] = label_value

                for search in self.fields['cmk_labels']:
                    if search.endswith('*'):
                        needle = search[:-1]
                        for label in labels.keys():
                            if label.startswith(needle):
                                label_name = label.replace('cmk/', '').replace('.', '_')
                                host_inventory['label_'+label_name] = labels[label]

            self.config_inventory[hostname] = host_inventory

    def run(self):
        """
        Run Sync
        """

        # Check if Rules are set,
        # If not, abort to prevent loss of data
        if not self.fields:
            raise CmkException("No Inventory Rules configured")

        print(f"{ColorCodes.OKBLUE}Started {ColorCodes.ENDC} with account "\
              f"{ColorCodes.UNDERLINE}{self.account_name}{ColorCodes.ENDC}")

        if app.config['CMK_GET_HOST_BY_FOLDER']:
            self.fetch_checkmk_folders()


        # Inventory for Status Information

        if self.fields.get('cmk_inventory'):
            self.get_hw_sw_inventory()

        #    columns.append('host_mk_inventory')

        if self.fields.get('cmk_services') or self.fields.get('cmk_labels'):
            # We fetch the Labels to have them available in get_attr_labels()
            self.get_cmk_services()

        if self.fields.get('cmk_service_labels'):
            self.get_service_labels()

        if self.fields.get('cmk_attributes') or self.fields.get('cmk_labels'):
            self.get_attr_labels()



        print(f"{ColorCodes.UNDERLINE}Write to DB{ColorCodes.ENDC}")

        # Resolve all syncer hosts in one query instead of one get_host per
        # name — a 10k-host inventorize shrinks from thousands of round
        # trips to a single collection scan.
        db_hosts = {}
        if self.found_hosts:
            for db_host in Host.objects(hostname__in=list(self.found_hosts)):
                db_hosts[db_host.hostname] = db_host

        for hostname in self.found_hosts:
            db_host = db_hosts.get(hostname)
            if db_host:
                db_host.update_inventory('cmk', self.config_inventory.get(hostname, {}))
                db_host.update_inventory('cmk_svc', self.status_inventory.get(hostname, {}))
                db_host.update_inventory('cmk_svc_labels',
                                         self.service_label_inventory.get(hostname, {}))
                db_host.update_inventory('cmk_hw_sw_inv', self.hw_sw_inventory.get(hostname, {}))
                db_host.save()
                print(f" {ColorCodes.OKGREEN}* {ColorCodes.ENDC} Updated {hostname}")
            else:
                print(f" {ColorCodes.FAIL}* {ColorCodes.ENDC} Not in Syncer: {hostname}")

    @staticmethod
    def _save_inventory_tree(hostname, flat_tree):
        """
        Persist the full flat HW/SW inventory tree as a HostInventoryTree
        side document. Called per host once the curated subset has been
        written to Host.inventory.

        Cheap-probes the existing ``tree_hash`` first: if it matches the
        SHA-256 of the new tree, no rewrite happens (the common steady-
        state path where Checkmk reports unchanged inventory). On change
        the current snapshot is shifted into ``previous_paths`` so the
        CMDB Tree tab can render a "changes since last import" banner.

        Returns True when the side document was written (caller can use
        this to decide whether the curated subset on Host.inventory
        also needs a save), False when nothing changed.
        """
        canonical = json.dumps(flat_tree or {}, sort_keys=True, default=str)
        new_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()

        probe = HostInventoryTree.objects(
            hostname=hostname, source=HW_SW_TREE_SOURCE,
        ).only('tree_hash').first()
        if probe and probe.tree_hash == new_hash:
            return False

        now = datetime.datetime.utcnow()
        paths = [
            HostInventoryTreePath(path=key, value=value)
            for key, value in (flat_tree or {}).items()
        ]
        existing = HostInventoryTree.objects(
            hostname=hostname, source=HW_SW_TREE_SOURCE,
        ).first()
        if existing:
            existing.previous_paths = list(existing.paths or [])
            existing.previous_update = existing.last_update
            existing.paths = paths
            existing.last_update = now
            existing.tree_hash = new_hash
            existing.save()
        else:
            HostInventoryTree(
                hostname=hostname,
                source=HW_SW_TREE_SOURCE,
                paths=paths,
                last_update=now,
                tree_hash=new_hash,
            ).save()
        return True
