"""
Dataflow Sync
"""
#pylint: disable=unnecessary-dunder-call
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from rich.console import Console

from application import logger
from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host

from application.modules.netbox.models import NetboxDataflowModels

class DictObj:
    def __init__(self, in_dict:dict):
        assert isinstance(in_dict, dict)
        for key, val in in_dict.items():
            if isinstance(val, (list, tuple)):
                setattr(self, key, [DictObj(x) if isinstance(x, dict) else x for x in val])
            else:
                setattr(self, key, DictObj(val) if isinstance(val, dict) else val)

class SyncDataFlow(SyncNetbox):
    """
    Netbox Data Flow
    """
    console = None
    headers = {}

    model_data_by_model = {}


    def handle_rule(self, rule, identify_field_name, model_name):
        """
        Handle Actions resulting from Rule

        Gets the current rules, which contain what the host has
        Checks if this exsist in den nb_data
        if not, just creates it, 
        if yes, checks if up to date,
        if not up to date, updates it.

        2) Compare with the nb_data
        3) Create if not in nb_data
        4) Update if given Fields are different
        """

        identify_field_value = rule['fields'][identify_field_name]['value']

        nb_data = self.model_data_by_model[model_name]


        api_url = f"{self.config['address']}/api/plugins/data-flows/{model_name}/"
        if identify_field_value not in nb_data:
            # Crate Object
            payload = self.get_update_keys(False, rule)
            new_header = self.headers
            resp = self.inner_request("POST", api_url, data=payload, headers=new_header)
            obj_id = resp.json()['id']
            payload['id'] = obj_id
            self.model_data_by_model[model_name][identify_field_value] = payload
            self.console(f"Create {identify_field_value}, new ID: {obj_id}")

        else:
            # Maybe Update Object
            current_object = self.model_data_by_model[model_name][identify_field_value]
            try:
                obj_id = current_object['id']
            except KeyError:
                print(current_object)
                raise
            # We don't wan't to have the ID in the update check
            del current_object['id']
            if payload := self.get_update_keys(current_object, rule):
                self.console(f"Update {identify_field_value}")
                update_url = f'{api_url}{obj_id}/'
                # It seams we need the full object here to do a update.
                # So use the changes to update the current_object
                current_object.update(payload)
                self.inner_request("PUT", update_url, data=current_object, headers=self.headers)
            current_object['id'] = obj_id



    def struct_current_model_data(self, identify_field, model_data, rule):
        """
        Parse Netbox Data into usable dict
        """
        out_dict = {}
        allowed_fields = list(rule['fields'].keys())
        allowed_fields.append('id')
        allowed_custom_fields = list(rule['custom_fields'].keys())
        for entry in model_data:
            field_name = entry[identify_field]
            subset = {k:v for k,v in entry.items() if k in allowed_fields}
            custom_fields = {k:v for k,v in entry['custom_fields'].items() \
                            if k in allowed_custom_fields}
            if custom_fields:
                subset['custom_fields'] = custom_fields
            out_dict[field_name] = subset
        return out_dict

    def process_model_data(self, model_name, model_data, rules):
        """
        Handle the Data and connect it to the Objects
        """
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Updating Data in Netbox", total=total)

            for db_object in db_objects:

                all_attributes = self.get_host_attributes(db_object, 'netbox_hostattribute')
                if not all_attributes:
                    progress.advance(task1)
                    continue

                object_config = self.get_host_data(db_object, all_attributes['all'])
                self.console(f" * Handle {db_object.hostname}")

                allowed_rules = [x.name for x in rules]
                if not 'rules' in object_config:
                    continue
                for rule in object_config['rules']:
                    if rule['rule'] not in allowed_rules:
                        continue

                    logger.debug(f"Working with {rule}")
                    try:
                        identify_field_name = [x for x,y in
                                        rule['fields'].items() if y['use_to_identify']][0]
                    except IndexError:
                        continue
                    if model_name not in self.model_data_by_model:
                        self.model_data_by_model[model_name] = \
                                self.struct_current_model_data(identify_field_name,
                                                               model_data,
                                                               rule)

                    self.handle_rule(rule, identify_field_name, model_name)
                progress.advance(task1)


    def get_current_data(self, model_name):
        """
        Collect the current Data for the given Model
        """
        result_collection = []
        console = Console()
        with console.status(f"Download current data for {model_name}"):
            api_url = f"{self.config['address']}/api/plugins/data-flows/{model_name}"
            resp = self.inner_request("GET", api_url, headers=self.headers)
            resp_data = resp.json()
            result_collection += resp_data['results']
            while resp_data.get('next'):
                next_url = resp_data['next']
                resp = self.inner_request("GET", next_url, headers=self.headers)
                resp_data = resp.json()
                result_collection += resp_data['results']
        return result_collection


    def sync_dataflow(self):
        """
        Sync Dataflow using custom API Endpoints
        """
        self.headers = {
            'Authorization': f"Token {self.config['password']}",
            'Content-Type': 'application/json',
        }
        for model_config in NetboxDataflowModels.objects(enabled=True):
            model_name = model_config.used_dataflow_model
            model_data = self.get_current_data(model_name)
            self.process_model_data(model_name, model_data, model_config.connected_rules)
