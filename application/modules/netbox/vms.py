"""
VM Syncronization
"""

from application.modules.netbox.netbox import SyncNetbox

from syncerapi.v1 import (
    cc,
    Host,
)

class SyncVMS(SyncNetbox):
    """
    Sync Netbox VMS
    """

    def get_vms(self, syncer_only=False):
        """
        Read full list of vms
        """
        print(f"{cc.OKGREEN} -- {cc.ENDC}Netbox: "\
              f"Read all VMs (Filter only CMDB Syncer: {syncer_only})")
        url = 'virtualization/virtual-machines/?limit=10000'
        if syncer_only:
            url += f"&cf_cmdbsyncer_id={self.config['_id']}"
        vms = self.request(url, "GET")
        return {x['display']:x for x in vms}

    def import_hosts(self):
        for hostname, data in self.get_vms().items():
            labels = self.extract_data(data)
            if 'rewrite_hostname' in self.config and self.config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname, self.config['rewrite_hostname'], labels)
            host_obj = Host.get_host(hostname)
            print(f"\n{cc.HEADER}Process VM: {hostname}{cc.ENDC}")
            host_obj.update_host(labels)
            do_save = host_obj.update_host(labels)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
