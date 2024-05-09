"""
Checkmk Downtime Sync
"""

import datetime

from application.modules.checkmk.config_sync import SyncConfiguration
from syncerapi.v1 import Host, cc

class CheckmkDowntimeSync(SyncConfiguration):
    """
    Sync Checkmk Downtimes
    """

    def set_downtime(self, cmk_site, host, start, end):
        """
        host: Hostname as in Checkmk
        start: Downtime start as a datetime object
        end: Downtime end as a datetime object
        """
        url = "domain-types/downtime/collections/host"
        data = {
            "host_name" : host,
            "downtime_type" : "host",
            "comment" : "Set by cmdbsyncer",
            "start_time" : start.isoformat(timespec='seconds'),
            "end_time" : end.isoformat(timespec='seconds'),
        }
        self.request(url, method="POST", data=data)

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


                self.get_current_cmk_downtimes(cmk_site, db_host.hostname)



    def get_current_cmk_downtimes(self, cmk_site, hostname):
        """
        Read Downtimes from Checkmk
        """

        url = f"domain-types/downtime/collections/all?"\
              f"host_name={hostname}&downtime_type=host&site_id={cmk_site}"
        response = self.request(url, method="GET")
        downtimes = response[0]['value']
        for downtime in downtimes:
            yield {
                "start_time" : datetime.datetime.fromisoformat(
                        downtime["extensions"]["start_time"]),
                "end_time" : datetime.datetime.fromisoformat(
                        downtime["extensions"]["end_time"]),
            }
