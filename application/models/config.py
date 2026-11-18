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

    # Attribute keys that collect the values of every CMDB template a
    # host carries instead of the first template winning. See
    # `application.models.host_templates.merged_attribute_keys`.
    merge_attributes = db.ListField(field=db.StringField())

    # First-steps wizard: set once an admin clicks "Don't show again" —
    # the admin start page then stops redirecting to the wizard even
    # while setup steps are still open.
    first_steps_dismissed = db.BooleanField(default=False)

    # Start of the latest `cron run_jobs` pass. The start page warns when
    # it is missing or old: then the system cron does not call the Syncer.
    last_cron_pass = db.DateTimeField()

    # Tolerate fields written by a newer version (e.g. a build on the same
    # database) so a downgrade doesn't fail loading the Config document.
    meta = {'strict': False}
