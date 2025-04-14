"""
Account
"""
from mongoengine import DENY
from cryptography.fernet import Fernet

from application import db, plugin_register
from application import app

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
    ('vmware_vcenter', "Vmware vCenter"),
    ('custom', "Custom Entries, like DBs"),
    ('prtg', "PRTG Monitoring"),
]


account_types.sort()


object_types = [
    ('auto', 'Autodetect by Plugin'),
    ('application', 'Application'),
    ('contact', 'Contact'),
    ('group', 'Group Object'),
    ('host', 'Host Object'),
    ('network', 'Network Object'),
    ('url', 'URL'),
    ('custom_1', 'Custom Type 1'),
    ('custom_2', 'Custom Type 2'),
    ('custom_3', 'Custom Type 3'),
    ('custom_4', 'Custom Type 4'),
    ('custom_5', 'Custom Type 5'),
    ('custom_6', 'Custom Type 6'),
    ('undefined', 'Undefined'),
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
    is_child = db.BooleanField(default=False)
    parent = db.ReferenceField(document_type='Account', reverse_delete_rule=DENY)
    is_object = db.BooleanField(default=False)
    object_type = db.StringField(choices=object_types)

    address = db.StringField()
    username = db.StringField()
    password = db.StringField() # Compatibility for existing ones
    password_crypted = db.StringField()

    custom_fields = db.ListField(field=db.EmbeddedDocumentField(document_type="CustomEntry"))
    plugin_settings = db.ListField(field=db.EmbeddedDocumentField(document_type="PluginSettings"))


    def set_password(self, password):
        """
        Encrypt Passwort in Store
        """
        f = Fernet(app.config['CRYPTOGRAPHY_KEY'])
        self.password_crypted = f.encrypt(str.encode(password)).decode('utf-8')
        self.save()

    def get_password(self):
        """
        Get Uncrypted Version of Password
        """
        if not self.password_crypted:
            uncrypted = self.password
            self.password = None
            self.set_password(uncrypted)
        f = Fernet(app.config['CRYPTOGRAPHY_KEY'])
        return f.decrypt(str.encode(self.password_crypted)).decode('utf-8')



    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }


    def __str__(self):
        return f"{self.name} ({self.typ})"
