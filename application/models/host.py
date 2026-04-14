"""
Host Model
"""
import re
import datetime
from mongoengine import Q, PULL
from mongoengine.errors import DoesNotExist
from application import db, app, logger
from application.modules.debug import ColorCodes as CC
from application.helpers.syncer_jinja import render_jinja
from application.models.account import object_types

class HostError(Exception):
    """
    Errors related to host updates or creation
    """

class DeprecatedError(Exception):
    """
    Raise for Deprecated functions
    """

class CmdbField(db.EmbeddedDocument):  # pylint: disable=too-few-public-methods
    """
    Field used in CMDB Mode
    """
    field_name = db.StringField(max_length=255)
    field_value = db.StringField(max_length=255)


# pylint: disable=too-many-instance-attributes,too-many-public-methods
class Host(db.Document):
    """
    Host
    """
    hostname = db.StringField(required=True, unique=True)
    sync_id = db.StringField()
    labels = db.DictField()
    inventory = db.DictField()

    cmdb_fields = db.ListField(field=db.EmbeddedDocumentField(document_type="CmdbField"))
    cmdb_templates = db.ListField(
        field=db.ReferenceField(document_type='Host', reverse_delete_rule=PULL))
    cmdb_match = db.StringField(max_length=255)

    # Class-level cache for template matching (populated via prefetch_templates())
    _template_match_cache = None


    no_autodelete = db.BooleanField(default=False)

    is_object = db.BooleanField(default=False)
    object_type = db.StringField(choices=object_types)

    source_account_id = db.StringField()
    source_account_name = db.StringField()

    available = db.BooleanField()

    last_import_seen = db.DateTimeField()
    last_import_sync = db.DateTimeField()
    create_time = db.DateTimeField()

    # If you assign a ID to you import,
    # that can later be used to simply cleanup
    # hosts with diffrent ids
    last_import_id = db.StringField()


    raw = db.StringField()

    folder = db.StringField() # Is just Checkmk related, better solution needed

    log = db.ListField(field=db.StringField())

    cache = db.DictField()


    meta = {
        'strict': False,
    }


    def is_valid_hostname(self):
        """
        Validate that the Hostname of the object is valid
        """
        if len(self.hostname) > 253:
            return False

        hostname_regex = \
                re.compile(r'^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$')

        return bool(hostname_regex.fullmatch(self.hostname))

    def __str__(self):
        return f"{self.object_type}: {self.hostname} ({self.source_account_name})"



    @staticmethod
    def delete_host_not_found_on_import(account, import_id, raw_filter=None):
        """
        Delete all hosts which are not available
        and match the given pattern
        """

        db_filter = Q(source_account_name=account) & Q(last_import_id__ne=import_id)
        user_filters = raw_filter.split('||')
        extra_filter = False
        for user_filter in user_filters:
            user_filter = user_filter.split(':', 1)
            if len(user_filter) == 2:
                field, field_value = map(str.strip, user_filter)
                if not extra_filter:
                    extra_filter = Q(**{field: field_value})
                else:
                    extra_filter &= Q(**{field: field_value})
        if extra_filter:
            full_filter = db_filter & (extra_filter)
        else:
            full_filter = db_filter
        Host.objects(full_filter).delete()


    @staticmethod
    def get_export_hosts():
        """
        Return all Objects for Exports
        """
        return Host.objects(available=True, is_object__ne=True)

    @staticmethod
    def objects_by_filter(object_list):
        """
        Return DB Objects Matching Filter
        """
        if not object_list:
            logger.debug("HOST FILTER OFF")
            return Host.objects(is_object__ne=True)
        logger.debug("HOST FILTER %s", object_list)
        return Host.objects(object_type__in=object_list)


    @staticmethod
    def get_host(hostname, create=True):
        """
        Returns the Host Object.
        Creates if not yet existing.

        Args:
            create (bool): Create a object if not yet existing (default)
        """
        hostname = hostname.strip()
        if not isinstance(hostname, str):
            raise HostError("Hostname field does not contain a string")
        if app.config['LOWERCASE_HOSTNAMES']:
            hostname = hostname.lower()
        if not hostname:
            return False
        try:
            return Host.objects.get(hostname=hostname)
        except DoesNotExist:
            pass

        if create:
            new_host = Host()
            new_host.hostname = hostname
            new_host.create_time = datetime.datetime.now()
            return new_host
        return False

    @staticmethod
    def rewrite_hostname(old_name, template, attributes):
        """
        Build a new Hostname based on Jinja Template
        """
        if template:
            return render_jinja(template, HOSTNAME=old_name, **attributes)
        return old_name


    @classmethod
    def prefetch_templates(cls):
        """
        Pre-load all matchable templates into a class-level cache.
        Call this once before processing many hosts to avoid repeated DB queries.
        Only fetches the fields needed for matching (id, cmdb_match).
        """
        cls._template_match_cache = list(
            cls.objects(object_type='template', cmdb_match__ne=None).only('id', 'cmdb_match')
        )

    @classmethod
    def clear_template_cache(cls):
        """Invalidate the template match cache (e.g. after template changes)."""
        cls._template_match_cache = None

    def get_cmdb_template(self):
        """
        Find and assign ALL matching CMDB templates based on label matching.

        Searches template objects (object_type='template') whose cmdb_match pattern
        matches against the labels of this host. ALL matching templates are collected
        and assigned to self.cmdb_templates.

        For performance with many hosts, call Host.prefetch_templates() once before
        processing a batch — the template list is then reused without further DB queries.

        Pattern syntax in cmdb_match:
        - Format: "label:value" for exact match (whitespace around colon is stripped)

        Returns:
            bool: True if at least one template was matched and assigned, False otherwise
        """
        if not self.labels:
            return False

        if Host._template_match_cache is not None:
            template_list = Host._template_match_cache
        else:
            try:
                template_list = list(
                    Host.objects(object_type='template', cmdb_match__ne=None)
                        .only('id', 'cmdb_match')
                )
            except Exception:  # pylint: disable=broad-exception-caught
                return False

        matched = []
        for template in template_list:
            if not template.cmdb_match or ':' not in template.cmdb_match:
                continue
            key, value = template.cmdb_match.split(':', 1)
            key, value = key.strip(), value.strip()
            if self.labels.get(key) == value:
                matched.append(template)

        if matched:
            self.cmdb_templates = matched
            return True
        return False

    def lock_to_folder(self, folder_name):
        """
        Lock System to given Folder
        Or remove it folder is False
        """
        if not folder_name:
            self.folder = None
        else:
            self.folder = folder_name
        self.save()

    def get_folder(self):
        """ Returns Folder if System is locked to one, else False """
        #@TODO make this CMK specific
        if self.folder:
            return self.folder
        return False

    def replace_label(self, key, value):
        """
        Replace or Create a single Label

        Args:
            key (string): Label Name
            value (string): Label Value
        """
        key = self._fix_key(key)
        if current_value := self.labels.get(key):
            if current_value == value:
                return
        self.labels[key] = value
        self.cache = {}

    def update_host(self, labels):
        """
        Overwrite all Labels on Hosts,
        but checks first if needed and also sets
        set_import_sync and import_seen as needed
        """
        if app.config['LABELS_ITERATE_FIRST_LEVEL']:
            for key, value in list(labels.items()):
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        labels[f'{key}_{sub_key}'] = sub_value
                    del labels[key]
        label_dict = dict(map(lambda kv: (self._fix_key(kv[0]), kv[1]), labels.items()))
        if self.get_labels() != label_dict:
            self.set_import_sync()
            self._set_labels(label_dict)
        self.set_import_seen()

    def _fix_key(self, key):
        key = str(key)
        if app.config['LOWERCASE_ATTRIBUTE_KEYS']:
            key = key.lower()
        if app.config['REPLACE_ATTRIBUTE_KEYS']:
            for needle, replacer in app.config['REPLACERS']:
                key = key.replace(needle, replacer)
        return key.replace(" ", "_").strip()

    def set_labels(self, _label_dictl):
        """
        Deprecated, migrate to update_host
        """
        raise DeprecatedError("Deprecated function set_labels(), migrate to update_host")

    def _set_labels(self, label_dict):
        """
        Overwrite all Labels on host

        Args:
            label_dict (dict): Key:Value pairs of labels
        """
        updates = []
        for key, value in label_dict.items():
            if self.labels.get(key) != value:
                updates.append(f"{key} to {value}")

        self.add_log(f"Label Change: {','.join(updates)}")
        self.labels = label_dict
        self.cache = {}

    def get_labels(self):
        """
        Return Hosts Labels dict.
        """
        return self.labels


    def set_inventory_attribute(self, key, value):
        """
        Set a Singe Attribute to the Inventory and Save it
        """
        if key in self.inventory:
            if self.inventory[key] != value:
                self.inventory[key] = value
                self.cache = {}
        else:
            self.inventory[key] = value
            self.cache = {}
        self.save()


    def _inventory_match_passes(self, new_data, config):
        """
        Feature: Inventorize Match Attribute.
        Returns True if the host should proceed with inventory update.
        """
        attr_match = config.get('inventorize_match_attribute')
        if not attr_match:
            return True
        attr_match = attr_match.split('=')
        if len(attr_match) == 2:
            host_attr, inv_attr = attr_match
        else:
            host_attr, inv_attr = attr_match[0], attr_match[0]
        try:
            attr_value = self.get_labels()[host_attr]
            inv_attr_value = new_data[inv_attr].strip()
        except KeyError:
            print(f" {CC.WARNING} * {CC.ENDC} Cant match Attribute."
                  f" Host has no Label {host_attr}")
            return False
        if attr_value != inv_attr_value:
            print(f" {CC.WARNING} * {CC.ENDC} Attribute '{host_attr}' "
                  f"is '{attr_value}' but '{inv_attr}' is '{inv_attr_value}'")
            return False
        return True

    def update_inventory(self, key, new_data, config=False):
        """
        Updates all inventory entries, with names who starting with given key.
        Ones not existing any more in new_data will be removed.
        Will also reset the Cache for the Host if some changes are detected.


        Args:
           key (string): Identifier for Inventory Attributes
           new_data (dict): Key:Value of Attributes.
        """
        if not key:
            raise ValueError("Inventory Key not set")
        if config and not self._inventory_match_passes(new_data, config):
            return

        check_dict = {}
        # Prevent RuntimeError: dictionary changed size during iteration
        for name, value in list(self.inventory.items()):
            # Delete all existing keys of type
            if name and name.startswith(key+"__"):
                check_dict[name] = value
                del self.inventory[name]

        update_dict = {
            f"{key}__{self._fix_key(x)}": y
            for x, y in (new_data or {}).items()
        }
        if app.config['LABELS_ITERATE_FIRST_LEVEL']:
            for upd_key, value in list(update_dict.items()):
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        update_dict[f'{upd_key}_{sub_key}'] = sub_value
                    del update_dict[upd_key]

        # We always set that, because we deleted before all with the key
        self.inventory.update(update_dict)

        # If the inventory is changed, the cache
        # is not longer valid
        if check_dict != update_dict:
            updates = [
                f"{item_key} to {value}"
                for item_key, value in update_dict.items()
                if check_dict.get(item_key) != value
            ]
            self.add_log(f"Inventory Change: {','.join(updates)}")
            self.cache = {}

    def get_inventory(self, key_filter=False):
        """
        Return all Inventory Data of Host.

        Args:
            key_filter (string): Filter for entries starting with this string
        """
        if key_filter:
            return {key: value for key, value in self.inventory.items() \
                            if key.startswith(key_filter)}

        return self.inventory

    def add_log(self, entry):
        """
        Add Log Entry to Host log.
        Can be shown in Frontend in the Host View.


        Args:
            entry (string): Message
        """
        entries = self.log[:app.config['HOST_LOG_LENGTH']-1]
        date = datetime.datetime.now().strftime(app.config['TIME_STAMP_FORMAT'])
        self.log = [f"{date} {entry}"] + entries

    def set_inventory_attributes(self, account_name):
        """
        Sets inventory-related attributes for the host.

        This method updates the `inventory` dictionary with the provided account name and
        the host's last seen and last sync timestamps.

        Args:
            account_name (str): The name of the account to associate with the inventory.

        Side Effects:
            Modifies the `inventory` attribute of the host instance by setting the following keys:
                - 'syncer_account': The provided account name.
                - 'syncer_last_seen': The value of `self.last_import_seen`.
                - 'syncer_last_sync': The value of `self.last_import_sync`.
        """
        self.inventory['syncer_account'] = account_name
        self.inventory['syncer_last_seen'] = self.last_import_seen
        self.inventory['syncer_last_sync'] = self.last_import_sync

    def ensure_cmdb_default_fields(self):
        """Ensure configured CMDB default fields exist on this host/object."""
        cmdb_models = app.config.get('CMDB_MODELS', {})
        object_fields = cmdb_models.get(self.object_type, {})
        global_fields = cmdb_models.get('all', {})

        configured_keys = list(object_fields.keys())
        configured_keys.extend([key for key in global_fields.keys() if key not in object_fields])

        if not configured_keys:
            return

        if self.cmdb_fields is None:
            self.cmdb_fields = []

        existing_keys = {
            entry.field_name for entry in self.cmdb_fields
            if getattr(entry, 'field_name', None)
        }

        for key in configured_keys:
            if key not in existing_keys:
                new_field = CmdbField()
                new_field.field_name = key
                self.cmdb_fields.append(new_field)

    def set_account(self, account_id=False, account_name=False,
                    account_dict=False, import_id="N/A"):
        """
        Mark Host with Account he was fetched with.
        Prevent Overwrites if Host is importet from multiple sources.

        Args:
            account_id (string): UUID of Account entry
            account_name (string): Name of account
            account_dict (dict): New: pass full Account Information

        Returns:
            status (bool): Should Object be saved or not

        """
        if self.source_account_name == 'cmdb':
            print("Host is locked since in CMDB Mode")
            return False
        if not account_id and not account_dict:
            raise ValueError("Either Set account_id or pass account_dict")

        is_object = False
        # That is the legacy behavior: Raise if not equal
        if not account_dict:
            if self.source_account_id and self.source_account_id != account_id:
                raise HostError(f"Host already importet by account {self.source_account_name}")
        else:
            # Get Name from Full dict
            account_id = account_dict['id']
            account_name = account_dict['name']
            is_object = account_dict.get('is_object', False)
            self.object_type = account_dict.get('object_type', 'auto')

        if self.object_type == 'host' and app.config['CHECK_FOR_VALID_HOSTNAME']:
            if not self.is_valid_hostname():
                raise HostError(f"{self.hostname} is not a valid Hostname,"
                                   "but object type for import is set to host")

        if account_dict['typ'] == 'from_api':
            self.no_autodelete = True

        if account_dict.get('cmdb_object'):
            self.no_autodelete = True
            self.get_cmdb_template()
            self.ensure_cmdb_default_fields()

        self.is_object = is_object
        self.last_import_id = import_id


        self.set_inventory_attributes(account_name)


        # Everthing Match already, make it short
        if self.source_account_id and self.source_account_id == account_id \
                            and self.source_account_name == account_name:
            return True

        # Nothing was set yet
        if not self.source_account_id:
            self.source_account_id = account_id
            self.source_account_name = account_name
            return True

        # If we are here, there is no match. Only Chance, this Account is master
        if account_dict.get('is_master'):
            self.source_account_id = account_id
            self.source_account_name = account_name
            return True

        # No, Account was not master. So we go
        return False


    def set_import_sync(self):
        """
        Mark that a sync for this host was needed to import
        """
        self.last_import_sync = datetime.datetime.now()
        # Delete Cache if new Data is imported
        self.cache = {}

    def set_import_seen(self):
        """
        Mark that this host was found on import
        """
        self.available = True
        self.last_import_seen = datetime.datetime.now()
