"""
IPAM Syncronisation
"""
from application.modules.netbox.netbox import SyncNetbox
from application.models.host import Host
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

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



    def get_payload(self, ip, fields):
        """
        Build Netbox Payload
        """
        return {
             "address": ip,
             "status": "active",
             #"role": "loopback",
             #"assigned_object_type": False,
             #"assigned_object_id": fields['assigned_obj_id']
           }




    def update_ip(self, current, ip, new_fields):
        """
        Send Update Request to Netbox
        """
        print(current)
        print("UPDATE")
        pass

    def create_ip(self, ip, field):
        """
        Send Create Request to Netbox
        """
        url = 'ipam/ip-addresses/'
        payload = self.get_payload(ip, field)
        self.request(url, "POST", payload)

    def sync_ips(self):
        """
        Sync IP Addresses
        """
        # Get current IPs
        current_ips = self.get_ips(syncer_only=True)
        new_ips = {}

        db_objects = Host.objects()
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Calculating all IPs", total=total)
            for db_host in db_objects:
                hostname = db_host.hostname

                all_attributes = self.get_host_attributes(db_host, 'netbox_hostattribute')
                if not all_attributes:
                    progress.advance(task1)
                    continue
                custom_rules = self.get_host_data(db_host, all_attributes['all'])

                if custom_rules.get('ignore_ip'):
                    progress.advance(task1)
                    continue

                if custom_rules:
                    if 'ip_address' in custom_rules and custom_rules['ip_address']:
                        new_ips[custom_rules['ip_address']] = {
                            'assigned': custom_rules.get('assigned', False),
                            'assigned_obj_id' : custom_rules.get('assigned_obj_id', 0),
                        }
                progress.advance(task1)
            
            task2 = progress.add_task("Send Requets to Netbox", total=len(new_ips))
            for ip, fields in new_ips.items():
                if ip in current_ips:
                    # Update IPs
                    self.update_ip(current_ips[ip], ip, fields)
                else:
                    self.create_ip(ip, fields)
                progress.advance(task2)
