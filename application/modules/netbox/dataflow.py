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

class Struct: #pylint: disable=missing-class-docstring
    def __init__(self, **entries):
        self.__dict__.update(entries)


class SyncDataFlow(SyncNetbox):
    """
    Netbox Data Flow
    """
    console = None
    headers = {}

    model_data_by_model = {}


    def handle_rule(self, rule, identify_field_name, model_name, nb_data):
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

        api_url = f"{self.config['address']}/api/plugins/data-flows/{model_name}"
        if identify_field_value not in nb_data:
            # Crate Object
            payload = self.get_update_keys(False, rule)
            logger.debug(f"Create Object with {payload}")
            self.inner_request("POST", api_url, headers=self.headers)

        else:
            # Maybe Update Object
            as_object = Struct(**nb_data[identify_field_value])
            payload = self.get_update_keys(as_object, rule)
            logger.debug(f"Update Object with {payload}")
            self.inner_request("PUT", api_url, headers=self.headers)


    def struct_current_model_data(self, identify_field, model_data):
        """
        Parse Netbox Data into usable dict
        """
        out_dict = {}
        for entry in model_data:
            out_dict[entry[identify_field]] = entry
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

                rules = self.get_host_data(db_object, all_attributes['all'])
                self.console(f" * Handle {db_object.thostname}")

                allowed_rules = [x.name for x in rules]
                for rule in rules['rules']:
                    if rule['rule'] not in allowed_rules:
                        continue

                    logger.debug(f"Working with {rule}")
                    try:
                        identify_field_name = [x for x,y in
                                        rule['fields'].items() if y['use_to_identify']][0]
                    except IndexError:
                        continue
                    if model_name not in self.model_data_by_model:
                        nb_data = self.struct_current_model_data(identify_field_name, model_data)
                    else:
                        nb_data = self.model_data_by_model[model_name]

                    self.handle_rule(rule, identify_field_name, model_name, nb_data)
                progress.advance(task1)


    def get_current_data(self, model_name):
        """
        Collect the current Data for the given Model
        """
        collection = []
        console = Console()
        with console.status(f"Download current data for {model_name}"):
            api_url = f"{self.config['address']}/api/plugins/data-flows/{model_name}"
            resp = self.inner_request("GET", api_url, headers=self.headers)
            resp_data = resp.json()
            collection =+ resp_data['results']
            while resp_data.get('next'):
                next_url = resp_data['next']
                resp = self.inner_request("GET", next_url, headers=self.headers)
                resp_data = resp.json()
                collection =+ resp_data['results']
        return collection


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
