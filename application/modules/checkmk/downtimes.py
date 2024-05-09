"""
Checkmk Downtime Sync
"""

import datetime

from application.modules.checkmk.config_sync import SyncConfiguration
from syncerapi.v1 import Host, cc

_weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

class CheckmkDowntimeSync(SyncConfiguration):
    """
    Sync Checkmk Downtimes
    """

    def timezone(self):
        return datetime.timezone.utc #TODO: implement localtime

    def ahead_days(self):
        today = datetime.date.today()
        one_day = datetime.timedelta(days=1)
        return [ today + i * one_day for i in range(14) ]

    def calculate_downtime_days(self, start_day, every):
        ahead_days = self.ahead_days()
        if every == "day":
            return ahead_days
        elif every == "workday":
            return [ day for day in ahead_days if day.isoweekday() not in [6, 7] ]
        elif every == "week":
            return [ day for day in ahead_days if _weekdays[day.weekday()] == start_day]
        else:
            return []

    def calculate_configured_downtimes(self, rule):
        now = datetime.datetime.now(datetime.timezone.utc)
        dt_time = datetime.time(hour=rule["start_time_h"],
                                minute=rule["start_time_m"],
                                tzinfo=self.timezone())
        dt_length = datetime.timedelta(hours=rule["duration_h"])
        for day in self.calculate_downtime_days(rule["start_day"], rule["every"]):
            dt_start = datetime.datetime.combine(day, dt_time)
            if dt_start < now:
                continue
            dt_end = dt_start + dt_length
            yield {
                "start" : dt_start,
                "end" : dt_end,
            }

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

                configured_downtimes = []
                for _rule_type, rules in host_actions.items():
                    for rule in rules:
                        if rule["every"] in [ "onces", "2nd_week" ]:
                            print(f"{cc.WARNING} *{cc.ENDC} Not implemented, need absolute starting point for this to work properly")
                            continue
                        configured_downtimes += list(self.calculate_configured_downtimes(rule))

                current_downtimes = list(
                        self.get_current_cmk_downtimes(cmk_site, db_host.hostname)
                        )

                for downtime in configured_downtimes:
                    for existing_dt in current_downtimes:
                        if not existing_dt["start"] - downtime["start"]:
                            if not existing_dt["end"] - downtime["end"]:
                                continue
                    self.set_downtime(cmk_site, db_host.hostname, downtime["start"], downtime["end"])



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
                "start" : datetime.datetime.fromisoformat(
                        downtime["extensions"]["start_time"]),
                "end" : datetime.datetime.fromisoformat(
                        downtime["extensions"]["end_time"]),
            }
