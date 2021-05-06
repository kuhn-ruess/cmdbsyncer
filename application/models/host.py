"""
Host Model
"""
# pylint: disable=no-member, too-few-public-methods, too-many-instance-attributes
import datetime
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


    def add_labels(self,label_dict):
        """
        Add new Label to hosts in case
        not yet existing
        """
        labels = []
        for key, value in label_dict.items():
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


    def set_hostname(self, hostname):
        """
        Set Hostname
        """
        self.hostname = hostname

    def set_account(self, account_id, account_name):
        """
        Set account Information
        """
        if self.account_id and self.account_id != account_id:
            raise HostError(f"Host {self.hostname} already importet by source {self.source_name}")
        self.account_id = account_id
        self.account_name = account_name

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


    def need_update(self, hours=24*7):
        """
        Does the the host need an update
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
