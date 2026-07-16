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

    # First-steps wizard: set once an admin clicks "Don't show again" —
    # the admin start page then stops redirecting to the wizard even
    # while setup steps are still open.
    first_steps_dismissed = db.BooleanField(default=False)
