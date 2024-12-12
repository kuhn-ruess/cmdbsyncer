"""
IPAM Syncronisation
"""
#pylint: disable=unnecessary-dunder-call
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host

from application.modules.netbox.models import NetboxDataflowModels


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
            task1 = progress.add_task("Updateing Objectst", total=total)
            for nb_object in nb_objects:
                custom_fields = False
                name = False
                for field in nb_object:
                    if field[0] == 'name':
                        name = field[1]
                    elif field[0] == 'custom_fields':
                        custom_fields = field[1]
                if custom_fields and name:
                    current_objects.update({name:custom_fields})
            for db_object in db_objects:
                hostname = db_object.hostname

                all_attributes = self.get_host_attributes(db_object, 'netbox_hostattribute')
                if not all_attributes:
                    progress.advance(task1)
                    continue
                rules = self.get_host_data(db_object, all_attributes['all'])
                allowed_rules = [x.name for x in model_data['connected_rules']]


                for rule in rules['rules']:
                    if rule['rule'] not in allowed_rules:
                        continue

                    logger.debug(f"Working with {rule}")
                    query_field = [x['value'] for x in
                                    rule['fields'].values() if x['use_to_identify']][0]
                    logger.debug(f"Filter Query: {query_field}")

                    if query_field and query_field not in current_objects:
                        ### Create
                        self.console(f" * Create Object {query_field} from {hostname}")
                        payload = self.get_update_keys(False, rule)
                        logger.debug(f"Create Payload: {payload}")
                        self.nb.plugins.__getattr__('data-flows').\
                                    __getattr__(model_name).create(payload)
                        current_objects.update({query_field: {}})
                    else:
                        # @TODO Get CURRENT OBJECT
                        raise("CANT UPDATE OBJECTS YET")
                        payload = self.get_update_keys(current_obj, rule)
                        self.nb.plugins.__getattr__('data-flows').\
                                    __getattr__(model_name).create(payload)
                progress.advance(task1)

    def sync_dataflow(self):
        """
        Sync Dataflow Addresses
        """
        for model_data in NetboxDataflowModels.objects(enabled=True):
            model_name = model_data.used_dataflow_model
            #current_objects = \
            #        self.nb.plugins.__getattr__('data-flows').__getattr__(model_name).all()
            current_objects = []
            self.inner_update(current_objects, model_data)
