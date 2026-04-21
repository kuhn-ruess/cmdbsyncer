"""
Checkmk Sites
"""
from application.plugins.checkmk.cmk2 import CMK2
from syncerapi.v1 import cc, Host



class CheckmkSites(CMK2):
    """
    Sync Site Settings
    """
    name = "Sync Sites with Checkmk"
    source = "cmk_site_sync"

    def get_sites(self):
        """
        Get list of Checkmk Sites with ID and Name
        """
        url = "domain-types/site_connection/collections/all"
        cmk_sites, _ = self.request(url, method="GET")
        return cmk_sites['value']


    def import_sites(self):
        """
        Fetch Checkmk sites and import them as objects in the Syncer.
        """
        print(f"\n{cc.HEADER}Import Sites{cc.ENDC}")
        for site in self.get_sites():
            site_data = site['extensions']
            labels = {}
            labels.update(site_data['basic_settings'])
            object_name = labels['site_id']
            syncer_object = Host.get_host(object_name)
            syncer_object.update_host(labels)
            # Attach source-account metadata the same way every other
            # importer does — otherwise these objects miss conflict
            # protection, inventory sync attribution and cannot be
            # cleaned up via the normal account lifecycle.
            do_save = syncer_object.set_account(account_dict=self.config)
            if not do_save:
                print(f"{cc.OKBLUE} *{cc.ENDC} Site {object_name} "
                      "owned by different source, ignored")
                continue
            # set_account may overwrite object_type from the account
            # dict; force the site-specific markers after it.
            syncer_object.is_object = True
            syncer_object.object_type = 'cmk_site'
            syncer_object.save()
            print(f"{cc.OKGREEN} *{cc.ENDC} Site {object_name} updated.")
