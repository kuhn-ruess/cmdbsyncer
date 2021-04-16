"""
Rule
"""
# pylint: disable=no-member
from application import db


class Rule(db.Document):
    """
    Rule
    """


    name = db.StringField(required=True, unique=True)
    enabled = db.BooleanFied()

    meta = {
        'strict': False,
    }


