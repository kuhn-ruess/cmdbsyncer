"""
Log Entry
"""

from application import db

class LogEntry(db.Document): #pylint: disable=too-few-public-methods
    """Log Entry"""

    datetime = db.DateTimeField()
    message = db.StringField()
    type = db.StringField()
    raw = db.StringField()
    traceback = db.StringField()


    meta = {"strict" : False,
            "indexes": [
                {'fields': ['datetime'],
                 'expireAfterSeconds': 2592000
                }
            ]
           }
