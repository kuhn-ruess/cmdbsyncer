"""
Central Brain for Netbox Operations
"""
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

    @staticmethod
    def get_slug(name):
        """
        Return Slag Version of String
        """
        return slugify(name)

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
            if obj_type == 'string':
                return field_value
            ## Create the SUB Field
            name_field = sub_obj.get('name_field', 'name')
            create_obj = {name_field: field_value}
            logger.debug(f"B1) Obj: {create_obj}, Type: {obj_type}")
            allow_default = sub_obj.get('allow_default_value', True)
            if not allow_default and field_value == 'CMDB Syncer Not defined':
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
                if not new_name:
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


    def get_update_keys(self, current_obj, config, compare_ids=False):
        """
        Get Keys which need a Update
        """
        if not compare_ids:
            compare_ids = []
        update_fields = {}
        if not 'fields' in config:
            return {}
        field_config = self.get_field_config()
        for field, field_data in config['fields'].items():
            field_value = field_data['value']

            logger.debug(f"A1) update_keys: {field}, {field_value}")
            if field in config.get('do_not_update_keys',[]):
                continue


            if current_obj:
                logger.debug(f"A2 a) Have current_object: {current_obj}")
                current_field = self.get_nested_attr(current_obj, field)
            else:
                # In Case we create a new project, it still could be thats
                # we have data from subfields here, therefore check for it:
                logger.debug("A2 b) Dont Have current_object, check for subfield")
                current_field = False

            if not field_value or field_value == '':
                logger.debug("A3) Field Undefied Fallback")
                field_value = 'CMDB Syncer Not defined'
            if field_data.get('is_list'):
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
                    field_value = self.get_name_or_id(field, field_value, config)
                    #pylint: disable=singleton-comparison
                    if field_value == False:
                        continue
                    if '.' in field:
                        field = field.split('.')[0]
                    update_fields[field] = field_value

        if config.get('custom_fields'):
            update_fields['custom_fields'] = {}

            current_custom = None # Can be also None in getattr
            if current_obj:
                current_custom = getattr(current_obj, "custom_fields")
            if not current_custom:
                current_custom = {}

            for field, field_data in config['custom_fields'].items():
                new_value = field_data['value']

                try:
                    current_field = None
                    if field in  current_custom:
                        current_field = current_custom[field]

                    if field_data.get('is_list'):
                        current_field = []
                        if int(new_value) not in [x['id'] for x in current_field]:
                            # Maybe also for else:
                            logger.debug(f"update_custom_list_field: {field}, {new_value}")
                            current_field.append({'id': int(new_value)})
                            update_fields['custom_fields'][field] \
                                    = [{'id': x['id']} for x in current_field]
                    elif new_value != current_field:
                        logger.debug(f"update_custom_field: {field}, {new_value} from {current_field}")
                        update_fields['custom_fields'][field] = new_value
                except AttributeError:
                    logger.debug(f"Missing Custom Field: {field}")
            if not update_fields['custom_fields']:
                del update_fields['custom_fields']
        return update_fields
