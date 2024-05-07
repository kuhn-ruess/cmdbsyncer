"""
Checkmk Downtime Sync
"""


from application.modules.checkmk.config_sync import SyncConfiguration
from syncerapi.v1 import Host, cc

class CheckmkDowntimeSync(SyncConfiguration):
    """
    Sync Checkmk Downtimes
    """

    def export_downtimes(self):
        """
        Export Downtimes
        """
        # Collect Rules
        total = Host.objects.count()
        counter = 0
        for db_host in Host.objects():
            attributes = self.get_host_attributes(db_host, 'cmk_conf')
            if not attributes:
                continue
            process = 100.0 * counter / total

            host_actions = self.actions.get_outcomes(db_host, attributes['all'])
            if host_actions:

                print(f"\n{cc.OKBLUE}({process:.0f}%){cc.ENDC} {db_host.hostname}")
                counter += 1
                if not 'cmk__label_site' in attributes['all']:
                    print(f"{cc.WARNING} *{cc.ENDC} Host has no cmk Site info")
                    continue
                # This Attribute needs to be inventorized from Checkmk
                cmk_site = attributes['all']['cmk__label_site']

                for _rule_type, rules in host_actions.items():
                    print(rules)

                self.get_current_cmk_downtimes(db_host.hostname, cmk_site)



    def get_current_cmk_downtimes(self, hostname, cmk_site):
        """
        Read Downtimes from Checkmk
        """

        url = f"domain-types/downtime/collections/all?"\
              f"host_name={hostname}&downtime_type=host&site_id={cmk_site}"
        response = self.request(url, method="GET")
        print(response[0]['value'])
