"""
Checkmk Downtime Sync
"""

import datetime
import calendar
import multiprocessing
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application.modules.checkmk.cmk2 import CmkException, CMK2
from syncerapi.v1 import Host, cc, render_jinja

_weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

class CheckmkDowntimeSync(CMK2):
    """
    Sync Checkmk Downtimes
    """
    # Reset Log Details
    #log_details = []

    name = "Synced Checkmk Downtimes"
    source = "cmk_downtime_sync"

    def ahead_days(self, offset):
        """
        Calculate how many times ahead we start
        """
        today = datetime.datetime.now()
        if offset:
            today = today + datetime.timedelta(days=offset)
        return [ today + datetime.timedelta(days=i)  for i in range(14) ]

    def calculate_downtime_days(self, start_day, every, offset):
        """
        Calculate the number of days for the downtime
        """
        ahead_days = self.ahead_days(offset)
        if every == "day":
            return ahead_days
        if every == "workday":
            return [ day for day in ahead_days if day.isoweekday() not in [6, 7] ]
        if every == "week":
            return [ day for day in ahead_days if _weekdays[day.weekday()] == start_day]
        return []

    def calculate_downtime_dates(self, start_day, every, offset):
        """
        Calculate configured day for a datime,
        like first of month
        """
        #pylint: disable=too-many-locals
        if offset:
            start_day = _weekdays[_weekdays.index(start_day)+offset]

        every = int(every.replace('.', ''))

        now = datetime.datetime.now(datetime.timezone.utc)
        year = now.year
        month = now.month
        next_year = year
        if month == 12:
            next_year = year+1
        next_month = month % 12 + 1

        this_month_dates = [datetime.date(year, month, day) \
                            for day in range(1, calendar.monthrange(year, month)[1] + 1)]
        next_month_dates = [datetime.date(next_year, next_month, day) \
                        for day in range(1, calendar.monthrange(next_year, next_month)[1] + 1)]

        this_month_day_strings = [x.strftime('%a').lower() for x in this_month_dates]
        next_month_day_strings = [x.strftime('%a').lower() for x in next_month_dates]

        hit = 0
        for idx, day in enumerate(this_month_day_strings):
            if day == start_day:
                hit += 1
                if hit == every:
                    yield this_month_dates[idx]
                    break
        hit = 0
        for idx, day in enumerate(next_month_day_strings):
            if day == start_day:
                hit += 1
                if hit == every:
                    yield next_month_dates[idx]
                    break



    def calculate_configured_downtimes(self, rule, attributes):
        """
        Calculate the Downtime payload
        """
        #pylint: disable=too-many-locals
        start_hour = int(render_jinja(rule['start_time_h'], **attributes))
        start_minute = int(render_jinja(rule['start_time_m'], **attributes))
        end_hour = int(render_jinja(rule['end_time_h'], **attributes))
        end_minute = int(render_jinja(rule['end_time_m'], **attributes))
        start_day = rule['start_day']
        if rule['start_day_template']:
            start_day = render_jinja(rule['start_day_template'], **attributes)
        every = rule['every']
        if rule['every_template']:
            every = render_jinja(rule['every_template'], **attributes)

        duration = False
        if rule['duration_h']:
            duration = int(render_jinja(rule['duration_h']))

        offset = False
        if rule['offset_days']:
            offset = int(rule['offset_days'])
        if rule['offset_days_template']:
            offset = int(render_jinja(rule['offset_days_template'], **attributes))

        now = datetime.datetime.now(datetime.timezone.utc)
        dt_start_time = datetime.time(start_hour, start_minute, 0)
        dt_end_time = datetime.time(end_hour, end_minute, 0)


        downtime_comment = render_jinja(rule['downtime_comment'], **attributes)


        if every in ['day', 'workday', 'week']:
            for day in self.calculate_downtime_days(start_day, every, offset):
                dt_start = \
                        datetime.datetime.combine(day, dt_start_time)\
                            .astimezone(datetime.timezone.utc)
                dt_end = \
                        datetime.datetime.combine(day, dt_end_time)\
                            .astimezone(datetime.timezone.utc)

                if dt_start < now:
                    continue
                yield {
                    "start" : dt_start,
                    "end" : dt_end,
                    "duration": duration,
                    "comment": downtime_comment,
                }
        else:
            # Fancy Mode
            for day in self.calculate_downtime_dates(start_day, every, offset):
                dt_start = \
                        datetime.datetime.combine(day, dt_start_time)\
                            .astimezone(datetime.timezone.utc)
                dt_end = \
                        datetime.datetime.combine(day, dt_end_time)\
                        .astimezone(datetime.timezone.utc)
                if dt_start < now:
                    continue
                yield {
                    "start" : dt_start,
                    "end" : dt_end,
                    "duration": duration,
                    "comment": downtime_comment,
                }


    def set_downtime(self, host, downtime):
        """
        host: Hostname as in Checkmk
        start: Downtime start as a datetime object
        end: Downtime end as a datetime object
        """
        url = "domain-types/downtime/collections/host"
        data = {
            "host_name" : host,
            "downtime_type" : "host",
            "comment" : downtime['comment'],
            "start_time" : downtime['start'].isoformat(timespec='seconds'),
            "end_time" : downtime['end'].isoformat(timespec='seconds'),
        }
        if downtime['duration']:
            data['duration'] = int(downtime['duration'])
        try:
            self.request(url, method="POST", data=data)
            print(f"\n{cc.OKGREEN} *{cc.ENDC} Set Downtime for "\
                  f"{data['start_time']} ({data['comment']})")
        except CmkException as error:
            print(f"\n{cc.WARNING} *{cc.ENDC} Downtime failed: "\
                  f"{error}")

    def do_hosts_downtimes(self, hostname, host_actions, attributes):
        """
        Calls for one Hosts Downtime
        """
        try:
            configured_downtimes = []
            for _rule_type, rules in host_actions.items():
                for rule in rules:
                    configured_downtimes += \
                            list(self.calculate_configured_downtimes(rule, attributes['all']))

            current_downtimes = list(
                        self.get_current_cmk_downtimes(hostname)
                    )
            for downtime in configured_downtimes:
                if downtime not in current_downtimes:
                    self.set_downtime(hostname, downtime)
        except Exception as exp:
            self.log_details.append(('error', f'Exception {exp}'))
            print(f"Exception: {exp}")

    def run(self):
        """
        Export Downtimes
        """
        # Collect Rules
        total = Host.objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Calculating Downtimes", total=total)
            for db_host in Host.objects():
                hostname = db_host.hostname
                progress.console.print(f"- Started for {hostname}")
                attributes = self.get_host_attributes(db_host, 'cmk_conf')
                if not attributes:
                    progress.advance(task1)
                    continue

                host_actions = self.actions.get_outcomes(db_host, attributes['all'])
                if not host_actions:
                    progress.advance(task1)
                    continue
                self.do_hosts_downtimes(hostname, host_actions, attributes)

    def run_async(self):
        """
        Export Downtimes
        """
        #@TODO: Fix Error: AttributeError:
        # Can't pickle local object 'export_downtimes.<locals>.ExportDowntimes'
        # Collect Rules
        total = Host.objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Calculating Downtimes", total=total)
            with multiprocessing.Pool() as pool:
                for db_host in Host.objects():
                    hostname = db_host.hostname
                    progress.console.print(f"- Started for {hostname}")
                    attributes = self.get_host_attributes(db_host, 'cmk_conf')
                    if not attributes:
                        progress.advance(task1)
                        continue

                    host_actions = self.actions.get_outcomes(db_host, attributes['all'])
                    if not host_actions:
                        progress.advance(task1)
                        continue

                    x= pool.apply_async(self.do_hosts_downtimes,
                                     args=(hostname, host_actions, attributes),
                                     callback=lambda x: progress.advance(task1))

                    x.get()
                pool.close()
                pool.join()

    def get_current_cmk_downtimes(self, hostname):
        """
        Read Downtimes from Checkmk
        """

        url = f"domain-types/downtime/collections/all?"\
              f"host_name={hostname}&downtime_type=host"
        response = self.request(url, method="GET")
        downtimes = response[0]['value']
        for downtime in downtimes:
            yield {
                "start" : datetime.datetime.fromisoformat(
                        downtime["extensions"]["start_time"]),
                "end" : datetime.datetime.fromisoformat(
                        downtime["extensions"]["end_time"]),
                "comment" : downtime["extensions"]["comment"],
                "duration" : downtime["extensions"].get("duration", False),
            }
