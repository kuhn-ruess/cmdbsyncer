"""
Cron Jobs
"""
from application import db, cron_register

intervals = [
    ("10min", "Every 15 minute"), # Crond runs 15min, but the 10 min makes sure it runs everytime
    ("hour", "Every hour"),
    ("daily", "Once Daily"),
]

hours = [
    ('0', '00:00'),
    ('1', '01:00'),
    ('2', '02:00'),
    ('3', '03:00'),
    ('4', '04:00'),
    ('5', '05:00'),
    ('6', '06:00'),
    ('7', '07:00'),
    ('8', '08:00'),
    ('9', '09:00'),
    ('10', '10:00'),
    ('11', '11:00'),
    ('12', '12:00'),
    ('13', '13:00'),
    ('14', '14:00'),
    ('15', '15:00'),
    ('16', '16:00'),
    ('17', '17:00'),
    ('18', '18:00'),
    ('19', '19:00'),
    ('20', '20:00'),
    ('21', '21:00'),
    ('22', '22:00'),
    ('23', '23:00'),
    ('24', '24:00'),
]

class GroupEntry(db.EmbeddedDocument):
    """
    Cron Entry
    """
    name = db.StringField(required=True)
    command = db.StringField(choices=cron_register.keys(), required=True)
    account = db.ReferenceField(document_type='Account', required=True)


class CronGroup(db.Document):
    """
    Cron Croup
    """

    name = db.StringField(required=True, unique=True)

    interval = db.StringField(choices=intervals)
    custom_interval_in_minutes = db.IntField()
    timerange_from = db.StringField(choices=hours, default='0')
    timerange_to = db.StringField(choices=hours, default='24')
    jobs = db.ListField(field=db.EmbeddedDocumentField(document_type="GroupEntry"))

    render_jobs = db.StringField()

    enabled = db.BooleanField()
    run_once_next = db.BooleanField(default=False)
    sort_field = db.IntField(default=0)

    meta = {
        'strict': False,
    }


commands = [
    ('cmk-export_hosts', "Checkmk: Export Hosts"),
    ('cmk-export_groups', "Checkmk: Export Groups"),
    ('cmk-export_rules', "Checkmk: Export Rules"),
    ('ansible-manage_hosts', "Ansible: Manage Hosts"),
    ('ansible-manage_servers', "Ansible: Manage Servers"),
]

class CronStats(db.Document):
    """
    Cron Stats
    """

    group = db.StringField()
    next_run = db.DateTimeField()

    last_start = db.DateTimeField()
    is_running = db.BooleanField(default=False)
    last_ended = db.DateTimeField()
    failure = db.BooleanField(default=False)

    last_message = db.StringField()

    all_messages = db.StringField()


    meta = {
        'strict' : False
    }
