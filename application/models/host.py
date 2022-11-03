"""
Host Model
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
import datetime
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

    force_update = db.BooleanField(default=False)

    source_account_id = db.StringField()
    source_account_name = db.StringField()

    available = db.BooleanField()

    last_export = db.DateTimeField()

    last_import_seen = db.DateTimeField()
    last_import_sync = db.DateTimeField()


    folder = db.StringField()

    export_problem = False

    log = db.ListField(db.StringField())


    meta = {
        'strict': False,
    }


    @staticmethod
    def get_host(hostname, create=True):
        """
        Return existing Host or
        create a object and return it
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


    def set_export_problem(self, message):
        """
        Mark Host as Export problem
        """
        self.export_problem = True
        self.add_log(message)
        self.save()

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
        Replace given Label name with value
        """
        hit = False
        for label in self.labels:
            if label == key:
                self.labels[label] = value
                hit = True
        if not hit:
            self.labels[key] = str(value)

    def set_labels(self, label_dict):
        """
        Overwrites the Labels on this object
        """
        self.labels=label_dict

    def get_labels(self):
        """
        Return Labels
        in Dict Format
        """
        return self.labels


    def update_inventory(self, key, new_data):
        """
        Overwrite given Values only
        """
        # pylint: disable=unnecessary-comprehension
        # Prevent runtime error
        for name in [x for x in self.inventory.keys()]:
            # Delete all existing keys of type
            if name.startswith(key):
                del self.inventory[name]
        self.inventory.update(new_data)

    def get_inventory(self, key_filter=False):
        """
        Return Hosts Inventory Data.
        Used eg. for Ansible
        """
        if key_filter:
            return {key: value for key, value in self.inventory.items() \
                            if key.startswith(key_filter)}

        return self.inventory

    def get_attributes(self):
        """
        Return Labels and Inventory merged
        """
        labels = self.get_labels()
        labels.update(self.get_inventory)
        # Merge Custom Labels
        labels.udpate(CustomLabels().get_labels(self.hostname))
        return labels



    def add_log(self, entry):
        """
        Add a new Entry to the Host log
        """
        entries = self.log[:app.config['HOST_LOG_LENGTH']-1]
        date = datetime.datetime.now().strftime(app.config['TIME_STAMP_FORMAT'])
        self.log = [f"{date} {entry}"] + entries

    def set_account(self, account_id, account_name):
        """
        Set account Information
        """
        if self.source_account_id and self.source_account_id != account_id:
            raise HostError(f"Host {self.hostname} already importet by source {self.source_name}")
        self.source_account_id = account_id
        self.source_account_name = account_name


    def set_import_sync(self):
        """
        Called always when we Update data
        to this object on import
        """
        self.available = True
        self.last_import_sync = datetime.datetime.now()

    def set_import_seen(self):
        """
        Call when seen on the import source,
        even if no update happens
        """
        self.available = True
        self.last_import_seen = datetime.datetime.now()


    def set_source_not_found(self):
        """
        When not found anymore on source,
        this will be set
        """
        self.available = False
        self.add_log("Not found on Source anymore")

    def set_export_sync(self):
        """
        Mark that host was updated on Export Target
        """
        self.last_export = datetime.datetime.now()
        self.save()

    def need_import_sync(self, hours=24):
        """
        Check if the host needs to be synced
        from the import source
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
        Check if we need to Update this host
        on the target
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
