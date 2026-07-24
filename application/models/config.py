"""
Config for the Syncer
"""
from application import db
class Config(db.Document):  # pylint: disable=too-few-public-methods
    """
    Config Values
    """

    export_labels_list = db.ListField(field=db.StringField())
    export_inventory_list = db.ListField(field=db.StringField())

    # Tolerate fields written by a newer version (e.g. a 4.3 build on the
    # same database) so a downgrade doesn't fail loading the Config document.
    meta = {'strict': False}
