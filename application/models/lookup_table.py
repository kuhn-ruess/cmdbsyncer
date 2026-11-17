"""
Lookup Table
"""
# pylint: disable=too-few-public-methods
from application import db
from application.helpers.lookup_table import MODES, MODE_KEY_VALUE


class LookupTable(db.Document):
    """
    A pasted table that Jinja reads with ``lookup(table, key)``.

    ``entries`` holds the table as text, the way a rule's pasted list does
    (first line = column names, tab, ``;``, ``,`` or ``|`` separated, see
    ``application.modules.rule.list_source``). In Key / Value mode the
    first column is a unique key, the other columns are the values a
    template can ask for. A Table is a plain list of rows that a template
    loops over with ``lookup_rows(table)``.
    """
    name = db.StringField(required=True, unique=True)
    documentation = db.StringField()
    mode = db.StringField(choices=MODES, default=MODE_KEY_VALUE)
    entries = db.StringField()

    meta = {
        'strict': False,
    }
