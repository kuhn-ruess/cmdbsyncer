"""
IPAM Syncronisation
"""
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

    def inner_update(self, current_objects, model_data):
        """
        Update/ Create of objects
        """
        model_name = model_data.used_dataflow_model
        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Updateing Objectst", total=total)
            for db_object in db_objects:
                hostname = db_object.hostname

                all_attributes = self.get_host_attributes(db_object, 'netbox_hostattribute')
                if not all_attributes:
                    progress.advance(task1)
                    continue
                field_cfgs = self.get_host_data(db_object, all_attributes['all'])
                allowed_rules = [x.name for x in model_data['connected_rules']]
                for field_cfg in field_cfgs['entries']:
                    if field_cfg['by_rule'] not in allowed_rules:
                        continue

                    logger.debug(f"Working with {field_cfg}")
                    query = {x:y['value'] for x,y in
                                field_cfg['fields'].items() if y['use_to_identify']}
                    all_fields = {x:y['value'] for x,y in
                                field_cfg['fields'].items()}
                    logger.debug(f"Filter Query: {query}")
                    if nb_object := current_objects.get(**query):
                        # Update
                        if payload := self.get_update_keys(nb_object, all_fields):
                            self.console(f"* Update Object: ... on {hostname}")
                            nb_object.update(payload)
                        else:
                            self.console(f"* Already up to date ... on {hostname}")
                    else:
                        ### Create
                        self.console(f" * Create Object  on {hostname}")
                        payload = self.get_update_keys(False, all_fields)
                        logger.debug(f"Create Payload: {payload}")

                        self.nb.__getattribute__('data-flows').\
                                    __getattribute__(model_name).create(payload)
            progress.advance(task1)

    def sync_dataflow(self):
        """
        Sync Dataflow Addresses
        """
        for model_data in NetboxDataflowModels.objects(enabled=True):
            model_name = model_data.used_dataflow_model
            current_objects = \
                    self.nb.plugins.__getattr__('data-flows').__getattr__(model_name).all()
            self.inner_update(current_objects, model_data)
