"""
Contact Syncronisation
"""
from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from syncerapi.v1 import (
    cc,
)


class SyncContacts(SyncNetbox):
    """
    Contact Syncer
    """
    console = None




    def get_payload(self, fields):
        """
        Build Netbox Payload
        """
        payload = {
          #"group": {
          #  "name": "string",
          #  "slug": "VLF6pIubTngolExZ9Lc",
          #  "description": "string"
          #},
          #"name": "string",
          #"title": "string",
          #"phone": "string",
          #"email": "user@example.com",
          #"address": "string",
          #"link": "string",
          #"description": "string",
          #"comments": "string",
          #"tags": [
          #  {
          #    "name": "string",
          #    "slug": "iB9r-7YmQXFiOTYt0vxJFKS",
          #    "color": "5e04b8"
          #  }
          #],
          #"custom_fields": {
          #  "additionalProp1": "string",
          #  "additionalProp2": "string",
          #  "additionalProp3": "string"
          #}
        }

        for what in ['name', 'title', 'phone', 
                     'email', 'address', 'description']:
            if what in fields:
                payload[what] = fields[what]
        return payload

    def sync_contacts(self):
        """
        Sync Contacts
        """
        # Get current Contacts
        url = '/tenancy/contacts/'
        current_contacts = self.get_objects(url, syncer_only=True)
        new_contacts = {}
        db_objects = Host.objects()
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Collecting and set Contacts", total=total)
            for db_object in db_objects:
                object_name = db_object.hostname

                self.console(f'Handling Object: {object_name}')

                all_attributes = self.get_attributes(db_object, 'netbox_hostattribute')
                if not all_attributes:
                    progress.advance(task1)
                    continue
                custom_rules = self.get_host_data(db_object, all_attributes['all'])

                if custom_rules.get('ignore_contact'):
                    progress.advance(task1)
                    continue
            
                payload = self.get_payload(custom_rules)
                if payload['name'] in current_contacts:
                    # Update Contact
                    if update_keys := self.need_update(current_contacts[payload['name']], payload):
                        netbox_id = current_contacts[contact]['id']
                        url = f'tenancy/contacts/{netbox_id}'
                        self.update_object(url, payload)
                else:
                    url = 'tenancy/contacts/'
                    self.create_object(url, payload)
                progress.advance(task1)
