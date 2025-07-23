"""
Account
"""
from mongoengine import DENY
from cryptography.fernet import Fernet

from application import db, plugin_register
from application import app

account_types = [
    ('bmc_remedy', "BMC Remedy (WIP)"),
    ('cisco_dna', "Cisco DNA Account"),
    ('cmkv1', "Checkmk Version 1.x"),
    ('cmkv2', "Checkmk Version 2.x"),
    ('csv', "CSV File"),
    ('custom', "Custom Entries, like DBs"),
    ('external_restapi', "Remote Rest API"),
    ('i-doit', "i-doit API"),
    ('jdisc', "Jdisc Device Discovery System"),
    ('jira', "Jira CMDB"),
    ('jira_cloud', "Jira Cloud CMDB"),
    ('json', "Json File"),
    ('ldap', "Ldap Connect"),
    ('maintenance', "Maintanence Jobs"),
    ('mssql', "MSSQL Table"),
    ('mysql', "Mysql Table"),
    ('netbox', "Netbox Account"),
    ('odbc', "ODBC Conenctions like FreeTDS"),
    ('prtg', "PRTG Monitoring"),
    ('restapi', "Internal Rest API Credentials"),
    ('vmware_vcenter', "Vmware vCenter"),
    ('yml', "YML File"),
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
    Account model for storing account credentials and related settings.

    Fields:
        name (str): Unique name of the account.
        type (str): Type of the account, with backward compatibility for 'typ'.
        is_master (bool): Indicates if this account is a master account.
        is_child (bool): Indicates if this account is a child account.
        parent (Account): Reference to the parent account.
        is_object (bool): Indicates if this account represents an object.
        object_type (str): Type of object associated with the account.
        address (str): Address or endpoint for the account.
        username (str): Username for authentication.
        password (str): Plaintext password (for backward compatibility).
        password_crypted (str): Encrypted password.
        custom_fields (list): List of custom fields (CustomEntry).
        plugin_settings (list): List of plugin settings (PluginSettings).
        enabled (bool): Whether the account is enabled.

    Methods:
        set_password(password, key=False): Encrypts and stores the password.
        get_password(key=False): Decrypts and returns the password.
    """
    name = db.StringField(required=True, unique=True)
    # Migrate from 'typ' to 'type', keep backward compatibility
    type = db.StringField(choices=account_types, db_field='typ')

    # Added with 3.10.0
    @property
    def typ(self):
        """
        Returns the value of the 'type' attribute for backward compatibility.
        This method allows access to the 'type' attribute using the legacy 'typ' property.

        Returns:
            The value of the 'type' attribute.
        """
        # For backward compatibility: allow obj.typ to work
        return self.type

    @typ.setter
    def typ(self, value):
        self.type = value

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


    def set_password(self, password, key=False):
        """
        Encrypt Passwort in Store
        """
        if key:
            cryptography_key = key
        else:
            cryptography_key = app.config['CRYPTOGRAPHY_KEY']
        f = Fernet(cryptography_key)
        self.password_crypted = f.encrypt(str.encode(password)).decode('utf-8')
        self.save()

    def get_password(self, key=False):
        """
        Get Uncrypted Version of Password
        """
        if key:
            cryptography_key = key
        else:
            cryptography_key = app.config['CRYPTOGRAPHY_KEY']
        if not self.password_crypted:
            uncrypted = self.password
            self.password = None
            self.set_password(uncrypted)
        f = Fernet(cryptography_key)
        return f.decrypt(str.encode(self.password_crypted)).decode('utf-8')



    enabled = db.BooleanField()

    meta = {
        'strict': False,
    }


    def __str__(self):
        return f"{self.name} ({self.typ})"
