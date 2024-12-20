"""
IPAM Syncronisation
"""
#pylint: disable=unnecessary-dunder-call
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host

from application.modules.netbox.models import NetboxDataflowModels

class Struct:
    def __init__(self, entries):
        for key, value in entries.items():
            setattr(self, key, value)


class SyncDataFlow(SyncNetbox):
    """
    Netbox Data Flow
    """
    console = None

    def inner_update(self, nb_objects, model_data):
        """
        Update/ Create of objects
        """
        model_name = model_data.used_dataflow_model
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        current_objects = {}
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            total_nb = len(nb_objects)
            task1 = progress.add_task("Reading Objects from Netbox", total=total_nb)
            for nb_object in nb_objects:
                custom_fields = {}
                name = False
                fields = {}
                for field in nb_object:
                    if field[0] == 'name':
                        name = field[1]
                        fields['name'] = name
                    elif field[0] == 'custom_fields':
                        custom_fields = field[1]
                    else:
                        fields[field[0]] = field[1]
                if fields and name:
                    fields.update(custom_fields)
                    current_objects.update({name:fields})
                progress.advance(task1)

            task2 = progress.add_task("Sending objects to Netbox", total=total)
            for db_object in db_objects:
                hostname = db_object.hostname
                payloads = []

                all_attributes = self.get_host_attributes(db_object, 'netbox_hostattribute')
                if not all_attributes:
                    progress.advance(task1)
                    continue
                rules = self.get_host_data(db_object, all_attributes['all'])
                allowed_rules = [x.name for x in model_data['connected_rules']]
                self.console(f" * Handle {hostname}")


                for rule in rules['rules']:
                    if rule['rule'] not in allowed_rules:
                        continue

                    logger.debug(f"Working with {rule}")
                    try:
                        query_field = [x['value'] for x in
                                        rule['fields'].values() if x['use_to_identify']][0]
                    except IndexError:
                        continue
                    logger.debug(f"Filter Query: {query_field}")

                    if query_field and query_field not in current_objects:
                        ### Create
                        self.console(f" *    Create Object {query_field}")
                        payload = self.get_update_keys(False, rule)
                        logger.debug(f"Create Payload: {payload}")
                        self.nb.plugins.__getattr__('data-flows').\
                                    __getattr__(model_name).create(payload)
                        current_objects.update({query_field: {}})
                    elif query_field:
                        #if platform := current_objects[query_field]['systemplatform']:
                        #    print(platform)
                        current_obj = Struct(current_objects[query_field])
                        payload = self.get_update_keys(current_obj, rule)
                        payload['custom_fields'] = {}
                        payload['custom_fields']['systemplatform'] = [{'id': 4}] 
                        payload['name'] = query_field
                        payload['id'] = current_obj.id
                        #print(payload)
                        payloads.append(payload)
                    else:
                        self.log_details.append(('info', f'Empty field with {hostname}'))
                if payloads:
                    self.nb.plugins.__getattr__('data-flows').\
                                __getattr__(model_name).update(payloads)
                progress.advance(task2)

    def sync_dataflow(self):
        """
        Sync Dataflow Addresses
        """
        for model_data in NetboxDataflowModels.objects(enabled=True):
            model_name = model_data.used_dataflow_model
            current_objects = \
                    self.nb.plugins.__getattr__('data-flows').__getattr__(model_name).all()

            self.inner_update(current_objects, model_data)
