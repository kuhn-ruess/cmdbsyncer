from application.modules.plugin import Plugin
from application import logger
try:
    import pynetbox
except ImportError:
    logger.info("Info: Netbox Plugin was not able to load required modules")

class SyncNetbox(Plugin):
    """
    Netbox Base Class
    """

#   .-- Get Host Data
    def get_host_data(self, db_host, attributes):
        """
        Return commands for fullfilling of the netbox params
        """
        return self.actions.get_outcomes(db_host, attributes)
#.

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
        attributes = attr_chain.split(".")
        for attr in attributes:
            obj = getattr(obj, attr)
        return obj

    @staticmethod
    def get_slug(name):
        """
        Return Slag Version of String
        """
        replacers = [
            ('.', ''),
            (' ', '-'),
        ]
        for repl, target in replacers:
            name = name.replace(repl, target)
        return name.lower()

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

        logger.debug(f"0) Working on {field}")
        if sub_obj := translation.get(field):
            obj_type = sub_obj['type']
            if obj_type == 'string':
                return field_value
            ## Create the SUB Field
            name_field = sub_obj.get('name_field', 'name')
            create_obj = {name_field: field_value}
            logger.debug(f"1) Obj: {create_obj}, Type: {obj_type}")
            allow_default = sub_obj.get('allow_default_value', True)
            if not allow_default and field_value == 'CMDB Syncer Not defined':
                logger.debug("1a) Ditched value since its a default")
                return None
            if sub_obj['has_slug']:
                logger.debug("2) Field has slug")
                create_obj['slug'] = self.get_slug(field_value)
            if current := self.get_nested_attr(self.nb, obj_type).get(**create_obj):
                logger.debug(f"3) Found current ID value  {current.id}")
                outer_id = current.id
            else:
                logger.debug("4) Need to create a new id")
                if extra_fields := sub_obj.get('sub_fields'):
                    for extra_field in extra_fields:
                        create_obj[extra_field] = \
                                self.get_name_or_id(extra_field, field_value, config)
                new_obj = self.get_nested_attr(self.nb, obj_type).create(create_obj)
                logger.debug(f"4b) New id is {new_obj.id}")
                outer_id = new_obj.id

            ## Sub Field was a subfield, so thats the first level
            if is_sub_model:
                sub_sub_obj = translation[is_sub_model]
                sub_obj_type = sub_sub_obj['type']
                logger.debug(f"5) Working with Submodel {obj_type}")
                new_name = config['fields'][is_sub_model]['value']
                if not new_name:
                    new_name = "CMDB Syncer Undefined"
                create_obj = {'name': new_name}
                if sub_sub_obj['has_slug']:
                    create_obj['slug'] = self.get_slug(new_name)
                if current := self.get_nested_attr(self.nb, sub_obj_type).get(**create_obj):
                    logger.debug("7) Found current Sub Field")
                    # Update the reference also if needed here
                    if getattr(current, field) != outer_id:
                        logger.debug("8) Need to Update reference field")
                        current.update({field: outer_id})
                    return current.id
                # Add reference to first field
                create_obj[field] = outer_id
                if extra_fields := sub_sub_obj.get('sub_fields'):
                    for extra_field in extra_fields:
                        create_obj[extra_field] = \
                                config['sub_fields'].get(extra_field,
                                {'value': 'CMDB Syncer Undefined'})['value']
                logger.debug(f"9) Creating object {create_obj}")
                new_obj = self.get_nested_attr(self.nb, sub_obj_type).create(create_obj)
                logger.debug(f"9 a) Returning New created Sub ID {new_obj.id}")
                return new_obj.id
            logger.debug(f"10) Returning First created ID {outer_id}")
            return outer_id
        # It's no reference, so direct value return
        logger.debug(f"11) Returning original Value {field_value}")
        return field_value


    def get_update_keys(self, current_obj, config):
        """
        Get Keys which need a Update
        """
        update_fields = {}
        for field, field_data in config['fields'].items():
            field_value = field_data['value']

            logger.debug(f"update_keys: {field}, {field_value}")
            if field in config.get('do_not_update_keys',[]):
                continue


            if current_obj:
                current_field = self.get_nested_attr(current_obj, field)
            else:
                # In this case we create a new object
                current_field = False
            if not field_value or field_value == '':
                field_value = 'CMDB Syncer Not defined'
            if field_data.get('is_list'):
                if not current_field:
                    current_field = []

                if field_value not in current_field:
                    current_field.append(field_value)
                    update_fields[field] = current_field
            else:
                if str(field_value).lower() != str(current_field).lower():
                    logger.debug(f'{field}: {repr(current_field)} -> {repr(field_value)}')
                    field_value = self.get_name_or_id(field, field_value, config)
                    if '.' in field:
                        field = field.split('.')[0]
                    update_fields[field] = field_value

        if config.get('custom_fields'):
            update_fields['custom_fields'] = {}
            custom_field_values = dict({x:y['value'] for x,y in config['custom_fields'].items()})
            if not current_obj:
                update_fields['custom_fields'] = custom_field_values
            else:
                if not hasattr(current_obj, 'custom_fields'):
                    update_fields['custom_fields'] = custom_field_values
                else:
                    for field, field_data in config['custom_fields'].items():
                        field_value = field_data['value']
                        logger.debug(f"update_custom_keys: {field}, {field_value}")
                        if current_field := current_obj['custom_fields'].get(field):
                            if current_field != field_value:
                                update_fields['custom_fields'][field] = field_value
                        else:
                            update_fields['custom_fields'][field] = field_value
            if not update_fields['custom_fields']:
                del update_fields['custom_fields']
        return update_fields
