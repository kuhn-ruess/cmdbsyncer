"""
Host Model
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
import datetime
import jinja2
from mongoengine.errors import DoesNotExist
from application import db, app

class HostError(Exception):
    """
    Errors related to host updates or creation
    """

class Target(db.EmbeddedDocument):
    """
    Target Stats
    """
    target_account_id = db.StringField()
    target_account_name = db.StringField()
    last_update = db.DateTimeField()

class Host(db.Document):
    """
    Host
    """
    hostname = db.StringField(required=True, unique=True)
    sync_id = db.StringField()
    labels = db.DictField()
    inventory = db.DictField()

    is_object = db.BooleanField(default=False)

    force_update = db.BooleanField(default=False)

    source_account_id = db.StringField()
    source_account_name = db.StringField()

    available = db.BooleanField()

    last_import_seen = db.DateTimeField()
    last_import_sync = db.DateTimeField()
    last_export = db.DateTimeField()


    raw = db.StringField()


    folder = db.StringField()

    export_problem = False

    log = db.ListField(field=db.StringField())

    cache = db.DictField()


    meta = {
        'strict': False,
    }



    @staticmethod
    def get_export_hosts():
        """
        Return all Objects for Exports
        """
        return Host.objects(available=True, is_object__ne=True)

    @staticmethod
    def get_host(hostname, create=True):
        """
        Returns the Host Object.
        Creates if not yet existing.

        Args:
            create (bool): Create a object if not yet existing (default)
        """
        try:
            return Host.objects.get(hostname=hostname)
        except DoesNotExist:
            pass

        if create:
            new_host = Host()
            new_host.hostname = hostname
            return new_host
        return False

    @staticmethod
    def rewrite_hostname(old_name, template, attributes):
        """
        Build a new Hostname based on Jinja Template
        """
        tpl = jinja2.Template(template)
        return tpl.render(HOSTNAME=old_name, **attributes)

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
        hit = False
        for label in self.labels:
            if label == key:
                self.labels[label] = value
                hit = True
        if not hit:
            self.labels[key] = str(value)

    def update_host(self, labels):
        """
        Overwrite all Labels on Hosts,
        but checks first if needed and also sets
        set_import_sync and import_seen as needed
        """
        if self.get_labels() != labels:
            self.set_import_sync()
            self.set_labels(labels)
        self.set_import_seen()

    def set_labels(self, label_dict):
        """
        Overwrite all Labels on host
        Will reset the cache, so check if realy needed before using

        Args:
            label_dict (dict): Key:Value pairs of labels
        """
        self.labels=dict({x:str(y) for x, y in label_dict.items()})
        self.cache = {}

    def get_labels(self):
        """
        Return Hosts Labels dict.
        """
        return self.labels


    def update_inventory(self, key, new_data):
        """
        Updates all inventory entries, with names who starting with given key.
        Ones not existing any more in new_data will be removed.
        Will also reset the Cache for the Host if some changes are detected.


        Args:
           key (string): Identifier for Inventory Attributes
           new_data (dict): Key:Value of Attributes.
        """
        # pylint: disable=unnecessary-comprehension
        # Prevent runtime error
        check_dict = {}
        for name, value in [(x,y) for x,y in self.inventory.items()]:
            # Delete all existing keys of type
            if name.startswith(key+"/"):
                check_dict[name] = value
                del self.inventory[name]

        update_dict = {f"{key}/{x}":y for x, y in new_data.items()}
        self.inventory.update(update_dict)

        # If the inventory is changed, the cache 
        # is not longer valid
        if check_dict != update_dict:
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

    def set_account(self, account_id=False, account_name=False, account_dict=False):
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

        self.is_object = is_object

        self.inventory['syncer_account'] = account_name

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
        if account_dict['is_master']:
            self.source_account_id = account_id
            self.source_account_name = account_name
            return True

        # No, Account was not master. So we go
        return False


    def set_import_sync(self):
        """
        Mark that a sync for this host was needed to import
        """
        self.available = True
        self.last_import_sync = datetime.datetime.now()
        # Delete Cache if new Data is imported
        self.cache = {}

    def set_import_seen(self):
        """
        Mark that this host was found on import
        """
        self.available = True
        self.last_import_seen = datetime.datetime.now()


    def set_source_not_found(self):
        """
        Mark when host was not found anymore.
        Exports will then ignore this system
        """
        self.available = False
        self.add_log("Not found on Source anymore")

    def set_export_sync(self):
        """
        Mark that the host was updated on export
        """
        self.last_export = datetime.datetime.now()
        self.save()

    def need_import_sync(self, hours=24):
        """
        Check when the last sync on import happend,
        and if a new sync is needed

        Args:
            hours (int): Time in which no update is needed
        """
        if not self.available:
            return True

        last_sync = self.last_import_sync
        timediff = datetime.datetime.now() - last_sync
        if divmod(timediff.total_seconds(), 3600)[0] > hours:
            return True
        return False


    def need_update(self, hours=24*7):
        """
        Check if we want to force an Update on a possible Targe.
        Args:
            hours (int): Time in which no update is needed
        """
        last_export = self.last_export
        if not last_export:
            return True
        if self.force_update:
            self.force_update = False
            self.save()
            return True
        timediff = datetime.datetime.now() - self.last_export
        if divmod(timediff.total_seconds(), 3600)[0] > hours:
            return True
        return False
