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
    console = None

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
        payload = {
             'address': ip,
             'status': 'active',
             'assigned': fields.get('assigned', False),
             'assigned_object_type': fields['assigned_obj_type'],
             'assigned_object_id': fields['assigned_obj_id'],
           }

        if fields['ip_family'] == 'ipv4':
            payload['family'] = {
                'value': 4,
                'label': 'IPv4',
            }
        else:
            payload['family'] = {
                'value': 6,
                'label': 'IPv6',
            }
        return payload




    def update_ip(self, netbox_id, payload):
        """
        Send Update Request to Netbox
        """
        url = f'ipam/ip-addresses/{netbox_id}'
        self.request(url, 'PATCH', payload)
        self.console(f' - Updated IP Address with ID {netbox_id}')

    def create_ip(self, ip, payload):
        """
        Send Create Request to Netbox
        """
        url = 'ipam/ip-addresses/'
        self.request(url, "POST", payload)
        self.console(f' - Created IP Address {payload["address"]}')

    def sync_ips(self):
        """
        Sync IP Addresses
        """
        # Get current IPs
        current_ips = self.get_ips(syncer_only=True)
        new_ips = {}

        db_objects = Host.get_export_hosts()
        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Calculating all IPs", total=total)
            for db_host in db_objects:
                hostname = db_host.hostname

                self.console(f'Hanling: {hostname}')

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
                            'ip_family': custom_rules.get('ip_family', 'ipv4'),
                            'assigned': custom_rules.get('assigned', False),
                            'assigned_obj_id' : custom_rules.get('assigned_obj_id', 0),
                            'assigned_obj_type' : custom_rules.get('assigned_obj_type', 0),
                        }
                progress.advance(task1)
            
            task2 = progress.add_task("Send Requets to Netbox", total=len(new_ips))
            for ip, fields in new_ips.items():
                payload = self.get_payload(ip, fields)
                if ip in current_ips:
                    # Update IPs
                    if update_keys := self.need_update(current_ips[ip], payload):
                        self.update_ip(current_ips[ip]['id'], payload)
                else:
                    self.create_ip(ip, payload)
                progress.advance(task2)
