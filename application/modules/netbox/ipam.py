"""
IPAM Syncronisation
"""
from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host

from syncerapi.v1 import (
    cc,
)


class SyncIPAM(SyncNetbox):
    """
    IP Syncer
    """

    def get_ips(self, syncer_only=False):
        """
        Read full list of IPs
        """
        print(f"{cc.OKGREEN} -- {cc.ENDC}Netbox: "\
              f"Read all IPs (Filter only CMDB Syncer: {syncer_only})")
        url = 'ipam/ip-addresses/'
        if syncer_only:
            url += f"?cf_cmdbsyncer_id={self.config['_id']}"
        ips = self.request(url, "GET")
        return {x['display']:x for x in ips}

    def sync_ips(self):
        """
        Sync IP Addresses
        """
        # Get current IPs
        current_ips = self.get_ips(syncer_only=True)

        print(current_ips)

        # Update IPs

        # Create IPs

        # Delete IPs
