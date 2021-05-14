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

class Label(db.EmbeddedDocument):
    """ Label Object (CMK Style)"""
    key = db.StringField()
    value = db.StringField()

class Host(db.Document):
    """
    Host
    """


    hostname = db.StringField(required=True, unique=True)

    force_update_on_target = db.BooleanField(default=False)


    available_on_source = db.BooleanField()
    last_seen_on_source = db.DateTimeField()

    disable_on_target = db.BooleanField(default=False)
    last_update_on_target = db.DateTimeField()

    account_id = db.StringField()
    account_name = db.StringField()


    labels = db.ListField(db.EmbeddedDocumentField(Label))

    log = db.ListField(db.StringField())


    meta = {
        'strict': False,
    }


    @staticmethod
    def get_host(hostname):
        """
        Return existing Host or
        create a object and return it
        """
        try:
            return Host.objects.get(hostname=hostname)
        except DoesNotExist:
            pass

        new_host = Host()
        new_host.hostname = hostname
        return new_host



    def add_labels(self,label_dict):
        """
        Add new Label to hosts in case
        not yet existing
        """
        labels = []
        for key, value in label_dict.items():
            if not value:
                continue
            label = Label()
            label.key = key
            label.value = value
            labels.append(label)
        self.labels = labels

    def get_labels(self):
        """
        Return Labels
        in Dict Format
        """
        return dict({x.key:x.value for x in self.labels})

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
        if self.account_id and self.account_id != account_id:
            raise HostError(f"Host {self.hostname} already importet by source {self.source_name}")
        self.account_id = account_id
        self.account_name = account_name
        self.set_source_update()

    def set_source_update(self):
        """
        Called all the time when found on
        """
        self.available_on_source = True
        self.last_seen_on_source = datetime.datetime.now()

    def set_source_not_found(self):
        """
        When not found anymore on source,
        this will be set
        """
        self.available_on_source = False
        self.add_log("Not found on Source anymore")

    def need_sync(self, hours=24):
        """
        Check if the host needs to be synced
        from the source
        """
        if not self.available_on_source:
            return True
        timediff = datetime.datetime.now() - self.last_seen_on_source
        if divmod(timediff.total_seconds(), 3600)[0] > hours:
            return True
        return False


    def need_update(self, hours=24*7):
        """
        Check if we need to Update this host
        on the target
        """
        if not self.last_update_on_target:
            return True
        if self.force_update_on_target:
            self.force_update_on_target = False
            self.save()
            return True
        timediff = datetime.datetime.now() - self.last_update_on_target
        if divmod(timediff.total_seconds(), 3600)[0] > hours:
            return True
        return False
