"""
Account
"""
from application import db, plugin_register

account_types = [
    ('cmkv1', "Checkmk Version 1.x"),
    ('cmkv2', "Checkmk Version 2.x"),
    ('csv', "CSV File"),
    ('json', "Json File"),
    ('jira', "Jira CMDB"),
    ('jira_cloud', "Jira Cloud CMDB"),
    ('jdisc', "Jdisc Device Discovery System"),
    ('mysql', "Mysql Table"),
    ('mssql', "MSSQL Table"),
    ('odbc', "ODBC Conenctions like FreeTDS"),
    ('ldap', "Ldap Connect"),
    ('netbox', "Netbox Account"),
    ('i-doit', "i-doit API"),
    ('cisco_dna', "Cisco DNA Account"),
    ('bmc_remedy', "BMC Remedy (WIP)"),
    ('restapi', "Internal Rest API Credentials"),
    ('external_restapi', "Remote Rest API"),
    ('maintenance', "Maintanence Jobs"),
    ('vmware', "Vmware vCenter"),
    ('custom', "Custom Entries, like DBs"),
]


account_types.sort()


object_types = [
    ('auto', 'Autodetect by Plugin'),
    ('undefined', 'Undefined'),
    ('host', 'Host Object'),
    ('group', 'Group Object'),
    ('network', 'Network Object'),
    ('application', 'Application'),
    ('contact', 'Contact'),
]


class PluginSettings(db.EmbeddedDocument):
    """
    Custom Attributes for Setup
    """
    plugin = db.StringField(choices=plugin_register)
    object_filter = db.ListField(field=db.StringField(choices=object_types))

class CustomEntry(db.EmbeddedDocument):
    """
    Custom Attributes for Setup
    """
    name = db.StringField(max_len=155)
    value = db.StringField()

class Account(db.Document):
    """
    Account
    """
    name = db.StringField(required=True, unique=True)
    typ = db.StringField(choices=account_types)
    is_master = db.BooleanField(default=False)
    is_object = db.BooleanField(default=False)
    object_type = db.StringField(choices=object_types)

    address = db.StringField()
    username = db.StringField()
    password = db.StringField()

    custom_fields = db.ListField(field=db.EmbeddedDocumentField(document_type="CustomEntry"))
    plugin_settings = db.ListField(field=db.EmbeddedDocumentField(document_type="PluginSettings"))


    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }


    def __str__(self):
        return f"{self.name} ({self.typ})"
