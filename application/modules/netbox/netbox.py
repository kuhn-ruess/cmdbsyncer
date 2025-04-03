"""
Central Brain for Netbox Operations
"""
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn


from application.models.host import Host
from application.modules.plugin import Plugin
from application import logger

try:
    import pynetbox
    from slugify import slugify
except ImportError:
    logger.info("Info: Netbox Plugin was not able to load required modules")

class SyncNetbox(Plugin):
    """
    Netbox Base Class
    """
    set_syncer_id = False

#   . -- Init
    def __init__(self, account):
        """ INIT """
        self.console = print # Fallback

        super().__init__(account)
        if self.config:
            # Not needed in Debug_host Mode
            self.nb = pynetbox.api(self.config['address'], token=self.config['password'])
            verify = False
            if 'true' in self.config.get('verify_cert', 'true').lower():
                verify = True
            self.nb.http_session.verify = verify
#.
#   . -- Helpers
    @staticmethod
    def get_field_config():
        """
        Return Fields needed for Devices
        """
        return {}


    @staticmethod
    def get_nested_attr(obj, attr_chain):
        """
        Parse nested Object
        """
        try:
            attributes = attr_chain.split(".")
            for attr in attributes:
                obj = getattr(obj, attr)
            return obj
        except AttributeError:
            logger.debug(f"Attribute Error: {obj} -> {attr_chain}")
        return False

    @staticmethod
    def get_slug(name):
        """
        Return Slag Version of String
        """
        return slugify(name)
#.
#   . -- Get Name or ID
    def get_name_or_id(self, field, field_value, config):
        """
        Get Netbox Object ID of given Object
        """
        translation = self.get_field_config()

        is_sub_model = False
        if '.' in field:
            splitted = field.split('.')
            field = splitted[1]
            is_sub_model = splitted[0]

        logger.debug(f"B0) Working on {field}")
        if sub_obj := translation.get(field):
            obj_type = sub_obj['type']
            if not field_value or obj_type == 'string':
                return field_value

            ## Create the SUB Field
            name_field = sub_obj.get('name_field', 'name')
            create_obj = {name_field: field_value}
            logger.debug(f"B1) Obj: {create_obj}, Type: {obj_type}")
            allow_default = sub_obj.get('allow_default_value', True)
            if not allow_default and field_value in ['CMDB Syncer Not defined',
                                                     'Unknown', 'unknown', None]:
                logger.debug("B1a) Ditched value since its a default")
                return None
            if sub_obj['has_slug']:
                logger.debug("B2) Field has slug")
                create_obj['slug'] = self.get_slug(field_value)
            if current := self.get_nested_attr(self.nb, obj_type).get(**create_obj):
                logger.debug(f"B3) Found current ID value  {current.id}")
                outer_id = current.id
            elif name_field != 'id':
                # ID Fields mean reference, they are not created if not existing
                logger.debug(f"B4) Need to create a new id, did not find {create_obj}")
                if extra_fields := sub_obj.get('sub_fields'):
                    for extra_field in extra_fields:
                        create_obj[extra_field] = \
                                self.get_name_or_id(extra_field, field_value, config)
                new_obj = self.get_nested_attr(self.nb, obj_type).create(create_obj)
                logger.debug(f"B4b) New id is {new_obj.id}")
                outer_id = new_obj.id
            else:
                return False

            ## Sub Field was a subfield, so thats the first level
            if is_sub_model:
                sub_sub_obj = translation[is_sub_model]
                sub_obj_type = sub_sub_obj['type']
                logger.debug(f"B5) Working with Submodel {obj_type}")
                new_name = config['fields'][is_sub_model]['value']
                if new_name == '':
                    new_name = "CMDB Syncer Undefined"
                create_obj = {'name': new_name}
                if sub_sub_obj['has_slug']:
                    create_obj['slug'] = self.get_slug(new_name)
                if current := self.get_nested_attr(self.nb, sub_obj_type).get(**create_obj):
                    logger.debug("B7) Found current Sub Field")
                    # Update the reference also if needed here
                    if getattr(current, field) != outer_id:
                        logger.debug("B8) Need to Update reference field")
                        current.update({field: outer_id})
                    return current.id
                # Add reference to first field
                create_obj[field] = outer_id
                if extra_fields := sub_sub_obj.get('sub_fields'):
                    for extra_field in extra_fields:
                        create_obj[extra_field] = \
                                config['sub_fields'].get(extra_field,
                                {'value': 'CMDB Syncer Undefined'})['value']
                logger.debug(f"B9) Creating object {create_obj}")
                new_obj = self.get_nested_attr(self.nb, sub_obj_type).create(create_obj)
                logger.debug(f"B9 a) Returning New created Sub ID {new_obj.id}")
                return new_obj.id
            logger.debug(f"B10) Returning First created ID {outer_id}")
            return outer_id
        # It's no reference, so direct value return
        logger.debug(f"B11) Returning original Value {field_value}")
        return field_value
#.
#   . -- Get Update Keys

    def get_update_keys(self, current_obj, config, compare_ids=False):
        """
        Get Keys which need a Update
        """
        logger.debug(f"A0) Working with {config}")
        if not compare_ids:
            compare_ids = []
        update_fields = {}
        update_fields['custom_fields'] = {}
        if not 'fields' in config:
            return {}
        if self.set_syncer_id:
            syncer_data = {'cmdbsyncer_id': {'value': str(self.account_id)}}
            if 'custom_fields' not in config:
                config['custom_fields'] = syncer_data
            else:
                config['custom_fields'].update(syncer_data)

        for field, field_data in config['fields'].items():
            field_value = field_data['value']

            logger.debug(f"A1) update_keys: {field}, {field_value}")
            if field in config.get('do_not_update_keys',[]):
                continue


            if isinstance(current_obj, dict):
                # This is the Case when the Dataflow Plugin is used,
                # there we have no object but a dict.
                current_field = current_obj.get(field)
            elif current_obj:
                logger.debug(f"A2 a) Have current_object: {current_obj}")
                current_field = self.get_nested_attr(current_obj, field)
            else:
                logger.debug("A2 b) Dont Have current_object, check for subfield")
                current_field = False

            if field_value == '':
                logger.debug("A3) Field Undefied Fallback")
                field_value = 'CMDB Syncer Not defined'
            if field_data.get('is_list') or isinstance(current_field, list):
                logger.debug("A4) Is list field")
                if not current_field:
                    current_field = []

                if field_value not in [x['id'] for x in current_field]:
                    logger.debug(f"A5) Added id {field_value} to list")
                    current_field.append({'id': field_value})
                    update_fields[field] = current_field
            else:
                if field in compare_ids and current_field:
                    new_field = current_field.id
                    logger.debug(f'A5) {field} compared {current_field}->{new_field}')
                    current_field = new_field
                if str(field_value).lower() != str(current_field).lower():
                    logger.debug(f'A6) {field}: {repr(current_field)} -> {repr(field_value)}')
                    if field_value in [ None, 'Unknown', 'unknown',
                                       'CMDB Syncer Not defined'] and current_field:
                        continue
                    field_value = self.get_name_or_id(field, field_value, config)
                    #pylint: disable=singleton-comparison
                    if field_value == False:
                        continue
                    if '.' in field:
                        field = field.split('.')[0]
                    update_fields[field] = field_value

        if config.get('custom_fields'):

            current_custom = {}
            if isinstance(current_obj, dict):
                # This is the Case when the Dataflow Plugin is used,
                # there we have no object but a dict.
                current_custom = current_obj.get('custom_fields', {})
            elif current_obj:
                current_custom = getattr(current_obj, "custom_fields")


            for field, field_data in config['custom_fields'].items():
                new_value = field_data['value']

                try:
                    current_field = None
                    if field in current_custom:
                        current_field = current_custom[field]
                    else:
                        logger.debug(f"Field not found in {current_custom}")

                    if field_data.get('is_list'):
                        if not current_field:
                            current_field = []
                        search_ids = [x['id'] for x in current_field]
                        if int(new_value) not in search_ids:
                            # Maybe also for else:
                            logger.debug(f"upd_cst_list_field: {field}, {new_value}"\
                                         f" not in {search_ids}")
                            current_field.append({'id': int(new_value)})
                            update_fields['custom_fields'][field] \
                                    = [{'id': x['id']} for x in current_field]
                    elif new_value != current_field:
                        logger.debug(f"update_custom_field: {field}, {new_value}"\
                                     f" from {current_field}")
                        update_fields['custom_fields'][field] = new_value
                except AttributeError:
                    logger.debug(f"Missing Custom Field: {field}")
        if not update_fields['custom_fields']:
            del update_fields['custom_fields']
        logger.debug(f"A7) Final Keys to update {update_fields}")
        return update_fields
#.
#   . -- Generic Netbox Syncer Function


    def handle_nb_attributes(self, attributes):
        """
        Handle Attributes, and the cases when they are nested
        """
        out = {}
        for field, value in attributes.items():
            if field == 'site':
                region_id = value.region.id
                region_name = self.nb.dcim.regions.get(region_id)
                out['region'] = self.fix_value(region_name)
                out['site'] = self.fix_value(value)
            else:
                out[field] = self.fix_value(value)
        return out

    def fix_value(self, value):
        """
        Fix Nested Netbox Fields so that they 
        Stored as string

        Otherwise we would have a big reference to 
        the other field instead just the name
        """
        if str(type(value)).startswith("<class 'pynetbox"):
            value = str(value)
        if isinstance(value, list):
            new_list = []
            for list_value in value:
                new_list.append(self.fix_value(list_value))
            value = new_list
        return value

    def _handle_config(self, what, cfg, current_objects, name_field, progress, task):
        """
        Handle Single Entry of cfg
        """
        object_name = cfg['fields'][name_field]['value']
        if not object_name:
            progress.advance(task)
            return
        query = {
            name_field:  object_name,
        }
        logger.debug(f"Filter Query: {query}")
        if current_object := current_objects.get(**query):
            if payload := self.get_update_keys(current_object, cfg):
                self.console(f"* Update {what}: {object_name} {payload}")
                current_object.update(payload)
            else:
                self.console(f"* {what} {object_name} already up to date")
        else:
            ### Create
            self.console(f"* Create {what} {object_name}")
            payload = self.get_update_keys(False, cfg)
            logger.debug(f"Create Payload: {payload}")
            current_object = current_objects.create(payload)

    def sync_generic(self, what, current_objects,
                     name_field, list_mode=False, prevent_duplicates=False):
        """
        Generic Sync Function
        for Modules without special Need
        """

        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)
        total = db_objects.count()
        duplicate_list = []
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task(f"Updating Data for {what}", total=None)


            for db_object in db_objects:
                hostname = db_object.hostname
                try:
                    all_attributes = self.get_host_attributes(db_object, 'netbox')
                    if not all_attributes:
                        progress.advance(task1)
                        continue
                    cfg = self.get_host_data(db_object, all_attributes['all'])
                    if not cfg:
                        progress.advance(task1)
                        continue

                    if cfg.get('ignore'):
                        progress.advance(task1)
                        continue

                    if list_mode:
                        for sub_cfg in cfg[list_mode]:
                            if prevent_duplicates:
                                seach_field = sub_cfg['fields'][prevent_duplicates]['value']
                                if seach_field in duplicate_list:
                                    progress.advance(task1)
                                    continue
                                duplicate_list.append(seach_field)
                            self._handle_config(what, sub_cfg, current_objects,
                                                name_field, progress, task1)
                    else:
                        if prevent_duplicates:
                            seach_field = cfg['fields'][prevent_duplicates]['value']
                            if seach_field in duplicate_list:
                                progress.advance(task1)
                                continue
                            duplicate_list.append(seach_field)
                        self._handle_config(what, cfg, current_objects, name_field, progress, task1)



                except Exception as error:
                    if self.debug:
                        raise
                    self.log_details.append((f'export_error {hostname}', str(error)))
                    print(f" Error in process: {error}")

                progress.advance(task1)
