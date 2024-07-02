"""
Log Entry
"""

from application import db

class DetailEntry(db.EmbeddedDocument):
    """
    Detail Log Entry
    """
    #@TODO: Level should be something like entry_name
    level = db.StringField()
    message = db.StringField()

class LogEntry(db.Document): #pylint: disable=too-few-public-methods
    """Log Entry"""

    datetime = db.DateTimeField()
    message = db.StringField()
    affected_hosts = db.StringField()
    has_error = db.BooleanField(default=False)
    source = db.StringField()
    metric_duration_sec = db.IntField(default=None)
    details = db.ListField(field=db.EmbeddedDocumentField(document_type="DetailEntry"))
    traceback = db.StringField()


    meta = {"strict" : False,
            "indexes": [
                {'fields': ['datetime'],
                 'expireAfterSeconds': 2592000
                }
            ]
           }
