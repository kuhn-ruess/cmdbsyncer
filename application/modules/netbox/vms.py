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

    def import_hosts(self):
        for vm in self.nb.virtualization.virtual_machines.all():
            hostname = vm.name
            labels = vm.__dict__
            if 'rewrite_hostname' in self.config and self.config['rewrite_hostname']:
                hostname = Host.rewrite_hostname(hostname, self.config['rewrite_hostname'], labels)
            host_obj = Host.get_host(hostname)
            print(f"\n{cc.HEADER}Process VM: {hostname}{cc.ENDC}")
            host_obj.update_host(labels)
            do_save = host_obj.update_host(labels)
            do_save = host_obj.set_account(account_dict=self.config)
            if do_save:
                host_obj.save()
