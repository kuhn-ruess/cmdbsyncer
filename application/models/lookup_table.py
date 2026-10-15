"""
Lookup Table
"""
# pylint: disable=too-few-public-methods
from application import db


class LookupTable(db.Document):
    """
    A pasted table that Jinja reads with ``lookup(table, key)``.

    ``entries`` holds the table as text, the way a rule's pasted list does
    (first line = column names, tab, ``;``, ``,`` or ``|`` separated, see
    ``application.modules.rule.list_source``). The first column is the key,
    the other columns are the values a template can ask for.
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    entries = db.StringField()

    meta = {
        'strict': False,
    }
