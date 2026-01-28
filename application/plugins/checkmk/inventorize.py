"""
Checkmk Inventorize
"""
import base64
import ast
import json

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
import multiprocessing

from application.models.host import Host, app
from application.plugins.checkmk.models import (
   CheckmkInventorizeAttributes
)
from application.plugins.checkmk.cmk2 import CMK2, CmkException
from application.modules.debug import ColorCodes


#@TODO Refactor into class with small methods
#pylint: disable=too-many-locals, too-many-branches, too-many-statements
#pylint: disable=too-many-nested-blocks

class InventorizeHosts(CMK2):
    """
    Host Inventorize in Checkmk
    """

    name = "Checkmk Inventory run"
    source = "cmk_inventorize"

    fields = {}
    config = {}

    found_hosts = []

    status_inventory = {}
    hw_sw_inventory = {}
    service_label_inventory = {}
    config_inventory = {}
    label_inventory = {}


    def add_host(self, host):
        """
        Just add if not in
        """
        if host not in self.found_hosts:
            self.found_hosts.append(host)

    def __init__(self, account):
        """Init"""

        super().__init__(account)

        for rule in CheckmkInventorizeAttributes.objects():
            self.fields.setdefault(rule.attribute_source, [])
            field_list = [x.strip() for x in rule.attribute_names.split(',')]
            self.fields[rule.attribute_source] += field_list


    def get_hw_sw_inventory_data(self, hostname, host_data):

        url = f"host_inv_api.py?host={hostname}&output_format=json"
        dict_inventory = self.request(url, method="GET", api_version="/")[0]['result'][hostname]
        if not dict_inventory:
            return False
        
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

        host_data[hostname] = return_data
        return True


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
            manager = multiprocessing.Manager()
            host_data = manager.dict()
            with multiprocessing.Pool() as pool:
                tasks = []
                for host_resp in response:
                    hostname = host_resp['extensions']['host_name']
                    self.add_host(hostname)
                    task = pool.apply_async(self.get_hw_sw_inventory_data,
                                     args=(hostname, host_data),
                                     callback=lambda x: progress.advance(task1))
                    tasks.append(task)

                for task in tasks:
                    try:
                        task.get(timeout=app.config['PROCESS_TIMEOUT'])
                    except multiprocessing.TimeoutError:
                        progress.console.print("- ERROR: Timeout for a object")
                    except Exception as error:
                        if self.debug:
                            raise
                        progress.console.print(f"- ERROR: Timeout error for object ({error})")
                pool.close()
                pool.join()
            self.hw_sw_inventory.update(dict(host_data))

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
            names = service['extensions']['label_names']
            values = service['extensions']['label_values']
            service_labels = zip(names, values)
            hostname = service['extensions']['host_name']
            self.add_host(hostname)
            self.service_label_inventory.setdefault(hostname, {})
            for name, value in service_labels:
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
                for label_key, label_value in labels.items():
                    if label_key in self.fields['cmk_labels']:
                        label_key = label_key.replace('cmk/','')
                        host_inventory['label_'+label_key] = label_value

                for search in self.fields['cmk_labels']:
                    if search.endswith('*'):
                        needle = search[:-1]
                        for label in labels.keys():
                            if label.startswith(needle):
                                label_name = label.replace('cmk/','')
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

        # pylint: disable=consider-using-dict-items
        for hostname in self.found_hosts:
            db_host = Host.get_host(hostname, False)
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
