"""
Contact Syncronisation
"""
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host


class SyncContacts(SyncNetbox):
    """
    Contact Syncer
    """
    console = None

    def sync_contacts(self):
        """
        Sync Contacts
        """
        # Get current Contacts
        current_contacts = self.nb.tenancy.contacts
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

                if not custom_rules:
                    progress.advance(task1)
                    continue

                if custom_rules.get('ignore_contact'):
                    progress.advance(task1)
                    continue

                logger.debug(f"Working with {custom_rules}")
                name = custom_rules['fields']['name']
                if not name:
                    progress.advance(task1)
                    continue
                query = {
                    'name': name,
                }
                logger.debug(f"Contact Filter Query: {query}")
                if contact := current_contacts.get(**query):
                    # Update
                    if payload := self.get_update_keys(contact, custom_rules):
                        self.console(f"* Update Interface: for {db_object.hostname} {payload}")
                        contact.update(payload)
                    else:
                        self.console("* Netbox already up to date")
                else:
                    ### Create
                    self.console(f" * Create Device for {db_object.hostname}")
                    payload = self.get_update_keys(False, custom_rules)
                    logger.debug(f"Create Payload: {payload}")
                    contact = self.nb.tenancy.contacts.create(payload)
                progress.advance(task1)
