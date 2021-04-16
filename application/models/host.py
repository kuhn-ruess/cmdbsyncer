"""
Host Model
"""
# pylint: disable=no-member
import datetime
from application import db


class Host(db.Document):
    """
    Host
    """


    hostname = db.StringField(required=True, unique=True)

    force_update_on_target = db.BooleanField(default=False)


    available_on_source = db.BooleanField()
    last_seen_on_source = db.DateTimeField()
    last_update_on_source = db.DateTimeField()

    available_on_target = db.BooleanField()
    disable_on_target = db.BooleanField(default=False)
    last_update_on_target = db.DateTimeField()
    last_update_on_target = db.DateTimeField()

    source_id = db.StringField()
    source_name = db.StringField()


    log = db.ListField(db.StringField())


    meta = {
        'strict': False,
    }


    def need_update(self, hours=24*7):
        """
        Does the the host need an update
        """
        if not self.last_update_on_source:
            return True
        if self.force_update_on_target:
            self.force_update_on_target = False
            self.save()
            return True
        timediff = datetime.datetime.now() - self.last_update_on_source
        if divmod(timediff.total_seconds(), 3600)[0] > hours:
            return True
        return False
