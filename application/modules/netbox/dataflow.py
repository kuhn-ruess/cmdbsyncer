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


    def update_cache(self, data, model_name, identify_field_name):
        """
        Use the NB Response to Udpate local Cache
        """
        for line in data:
            if not line:
                continue
            if isinstance(line, str):
                continue
            if identify_field_name not in line:
                continue
            identify_field_value = line[identify_field_name]
            for what in ['created', 'display', 'last_updated', 'url']:
                try:
                    del line[what]
                except KeyError:
                    continue
            self.model_data_by_model[model_name][identify_field_value] = line


    def handle_rule_outcome(self, rule, identify_field_value,  model_name):
        """
        Handle Actions resulting from Rule

        Function is called once per Rule Outcome
        """


        nb_data = self.model_data_by_model[model_name]

        if identify_field_value not in nb_data:
            # Crate Object
            self.console(f" * Prepare CREATE: {identify_field_value}")
            payload = self.get_update_keys(False, rule)
            return payload, "create"
        # Maybe Update Object
        current_object = self.model_data_by_model[model_name][identify_field_value]
        if payload := self.get_update_keys(current_object, rule):
            self.console(f" * Prepare UPDATE {identify_field_value}")
            current_object['custom_fields'].update(payload['custom_fields'])
            current_object.update(payload)
            return current_object, 'update'
        return {}, False


    def process_syncer_objects(self, model_name, model_data, rules):
        """
        Handle the Data and connect it to the Objects
        """
        api_url = f"{self.config['address']}/api/plugins/data-flows/{model_name}/"
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        self.model_data_by_model[model_name] = {}
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Updating Data in Netbox", total=total)

            for db_object in db_objects:
                create_list = []
                update_list = []

                all_attributes = self.get_attributes(db_object, 'netbox')
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
                        identify_field_value = rule['fields'][identify_field_name]['value']
                    except IndexError:
                        continue

                    # Only get NB Data, if we not already have it from object before.
                    # Because from there, we keep and Update it in our memory
                    if identify_field_value not in self.model_data_by_model[model_name]:
                        self.update_cache(model_data, model_name, identify_field_name)

                    payload, what = self.handle_rule_outcome(rule, identify_field_value, model_name)
                    if what == 'create':
                        if payload and payload not in create_list:
                            create_list.append(payload)
                    elif what == 'update':
                        if payload and payload not in update_list:
                            update_list.append(payload)

                if create_list:
                    self.console('Send Creates')
                    response = self.inner_request('POST', api_url,
                                                  json=create_list, headers=self.headers)
                    self.update_cache(response.json(), model_name,  identify_field_name)

                if update_list:
                    self.console('Send Updates')
                    response = self.inner_request('PUT', api_url,
                                                  json=update_list, headers=self.headers)
                    self.update_cache(response.json(), model_name,  identify_field_name)

                progress.advance(task1)


    def get_model_data(self, model_name):
        """
        Collect the current Data for the given Model
        """
        result_collection = []
        console = Console()
        with console.status(f"Download current data for {model_name}"):
            api_url = f"{self.config['address']}/api/plugins/data-flows/{model_name}?limit=15000"
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
            model_data = self.get_model_data(model_name)
            self.process_syncer_objects(model_name, model_data, model_config.connected_rules)
