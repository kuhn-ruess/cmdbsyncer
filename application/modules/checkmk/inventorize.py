"""
Checkmk Inventorize
"""
import base64
import ast
import json

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application.models.host import Host, app
from application.modules.checkmk.models import (
   CheckmkInventorizeAttributes
)
from application.modules.checkmk.cmk2 import CMK2, CmkException
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
    account = ""
    config = {}

    found_hosts = []

    status_inventory = {}
    hw_sw_inventory = {}
    service_label_inventory = {}
    config_inventory = {}
    label_inventory = {}


    checkmk_folders = []

    def add_host(self, host):
        """
        Just add if not in
        """
        if host not in self.found_hosts:
            self.found_hosts.append(host)

    def fetch_checkmk_folders(self):
        """
        Fetch list of Folders in Checkmk
        """
        url = "domain-types/folder_config/collections/all"
        url += "?parent=/&recursive=true&show_hosts=false"
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Fetching Current Folders", start=False)
            api_folders = self.request(url, method="GET")
            for folder in api_folders[0]['value']:
                progress.update(task1, advance=1)
                path = folder['extensions']['path']
                self.checkmk_folders.append(path)

    def __init__(self, account):
        """Init"""

        super().__init__(account)

        for rule in CheckmkInventorizeAttributes.objects():
            self.fields.setdefault(rule.attribute_source, [])
            field_list = [x.strip() for x in rule.attribute_names.split(',')]
            self.fields[rule.attribute_source] += field_list




    def get_hw_sw_inventory(self):
        """ Query HW/SW Inventory"""
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting HW/SW Inventory")
        url = "domain-types/service/collections/all"

        params={
            "query":
               '{ "op": "=", "left": "description", "right": "Check_MK HW/SW Inventory"}',
            "columns": ['host_name', 'host_mk_inventory']
        }
        # We run that only on first line, thats the Checkmk_Service

        api_response = self.request(url, data=params, method="GET")
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Parsing HW/SW Inventory Data")
        for service in api_response[0]['value']:
            hostname = service['extensions']['host_name']
            self.add_host(hostname)
            self.hw_sw_inventory.setdefault(hostname, {})
            raw_inventory = service['extensions']['host_mk_inventory']['value'].encode('ascii')
            raw_decoded_inventory = base64.b64decode(raw_inventory).decode('utf-8')

            if raw_decoded_inventory:
                inv_raw = ast.literal_eval(raw_decoded_inventory)
                inv_parsed = {}
                # Parsing 3 Levels of HW/SW Inventory
                for node_name, node_content in inv_raw['Nodes'].items():
                    inv_parsed[node_name] = {}
                    if node_content['Attributes']:
                        for attr_name, attribute_value in \
                                                node_content['Attributes']['Pairs'].items():
                            inv_parsed[node_name][attr_name] = attribute_value
                    if node_content['Nodes']:
                        for sub_node_name, sub_node_content in node_content['Nodes'].items():
                            inv_parsed[node_name][sub_node_name] = {}
                            if sub_node_attributes := sub_node_content.get('Attributes'):
                                for attr_name, attribute_value in \
                                            sub_node_attributes['Pairs'].items():
                                    inv_parsed[node_name][sub_node_name][attr_name] = \
                                                                                attribute_value
                            if sub_node_nodes := sub_node_content.get('Nodes'):
                                for sub_sub_node_name, sub_sub_node_content in \
                                                                        sub_node_nodes.items():
                                    inv_parsed[node_name][sub_node_name][sub_sub_node_name] = {}
                                    if sub_sub_node_attributes := \
                                                        sub_sub_node_content.get('Attributes'):
                                        for attr_name, attribute_value in \
                                                    sub_sub_node_attributes['Pairs'].items():
                                            inv_parsed[node_name][sub_node_name]\
                                                [sub_sub_node_name][attr_name] = attribute_value


                # Get the wanted fiels out of the parsed data
                for needed_fields in self.fields['cmk_inventory']:
                    data = inv_parsed
                    fields = needed_fields.split('.')
                    data_name = "_".join(fields)
                    for path in fields:
                        if not data:
                            continue
                        data = data.get(path)
                    if isinstance(data, dict):
                        for sub_field, sub_value in data.items():
                            self.hw_sw_inventory[hostname][f"{data_name}_{sub_field}"] = sub_value
                    elif data:
                        self.hw_sw_inventory[hostname][data_name] = data

    def get_cmk_services(self):
        """ Get CMK Services"""
        print(f"{ColorCodes.OKBLUE} *{ColorCodes.ENDC} Collecting Service Data")
        url = "domain-types/service/collections/all"

        columns = ['host_name', 'description', 'state', 'plugin_output', 'host_labels']

        expr = []
        expr.append({"op": "=", "left": "description", "right": "Check_MK"})
        for field in self.fields['cmk_services']:
            expr.append({"op": "=", "left": "description", "right": field})

        query = {
            "op": "or",
            "expr": expr,
        }
        params={
            "query": str(json.dumps(query)),
            "columns": columns
        }

        api_response = self.request(url, data=params, method="GET")
        for service in api_response[0]['value']:
            hostname = service['extensions']['host_name']
            self.add_host(hostname)
            service_description = service['extensions']['description'].lower().replace(' ', '_')
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
        api_response = self.request(url, data=params, method="GET")
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
            pass



        url = "domain-types/host_config/collections/all?effective_attributes=true"
        api_hosts = self.request(url, method="GET")
        for host in api_hosts[0]['value']:
            hostname = host['id']
            self.add_host(hostname)
            attributes = host['extensions']
            attributes.update(host['extensions']['effective_attributes'])

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
                labels.update(attributes['labels'])
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
              f"{ColorCodes.UNDERLINE}{self.account}{ColorCodes.ENDC}")

        if app.config['CMK_GET_HOST_BY_FOLDER']:
            self.fetch_checkmk_folders()


        # Inventory for Status Information

        if self.fields.get('cmk_inventory'):
            self.get_hw_sw_inventory()

        #    columns.append('host_mk_inventory')

        if self.fields.get('cmk_services'):
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
