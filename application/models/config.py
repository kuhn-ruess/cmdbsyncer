"""
Config for the Syncer
"""
from application import db
class Config(db.Document):
    """
    Config Values
    """

    export_labels_list = db.ListField(field=db.StringField())
    export_inventory_list = db.ListField(field=db.StringField())
