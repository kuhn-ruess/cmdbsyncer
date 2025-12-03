"""
Contact Syncronisation
"""
from .netbox import SyncNetbox

class SyncContacts(SyncNetbox):
    """
    Contact Syncer
    """
    console = None

    @staticmethod
    def get_field_config():
        """
        Return Fields needed for Devices
        """
        return {
            'group': {
                'type': 'tenancy.contact-groups',
                'has_slug' : True,
            },
        }

    def sync_contacts(self):
        """
        Sync Contacts
        """
        # Get current Contacts
        current_contacts = self.nb.tenancy.contacts
        self.sync_generic('Contact', current_contacts, 'name')
