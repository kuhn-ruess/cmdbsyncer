"""
Cron Jobs
"""
from application import db, cron_register

intervals = [
    ("10min", "Every 10 minute"),
    ("hour", "Every hour"),
    ("daily", "Once Daily"),
]

class GroupEntry(db.EmbeddedDocument):
    """
    Cron Entry
    """
    name = db.StringField()
    command = db.StringField(choices=cron_register.keys())
    account = db.ReferenceField('Account')


class CronGroup(db.Document):
    """
    Cron Croup
    """

    name = db.StringField(required=True, unique=True)

    interval = db.StringField(choices=intervals)
    jobs = db.ListField(db.EmbeddedDocumentField("GroupEntry"))

    render_jobs = db.StringField()

    enabled = db.BooleanField()

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


    meta = {
        'strict' : False
    }
