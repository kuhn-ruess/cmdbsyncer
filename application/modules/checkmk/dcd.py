"""
Checkmk DCD Manager
"""
from jinja2.exceptions import UndefinedError
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn
from application.modules.checkmk.config_sync import SyncConfiguration

from application import logger

from syncerapi.v1 import Host, render_jinja


class CheckmkDCDRuleSync(SyncConfiguration):
    """
    Sync Checkmk Downtimes
    """
    console = None
    all_rules = []

    name = "Synced DCD Rules"
    source = "cmk_dcd_rule_sync"


    def does_rule_exist(self, rule_id):
        """
        Check if Rule is existing
        """
        url = f"/objects/dcd/{rule_id}"
        response = self.request(url, method="GET")
        if response[0]:
            return True
        return False


    def build_timeranges(self, rule):
        """
        Return Timestamp ListField
        "exclude_time_ranges": [
          {
            "start": "11:00",
            "end": "13:00"
          }
        ],
        """
        timeranges = []
        for tr in rule['exclude_time_ranges']:
            timeranges.append({
                'start': f"{tr['start_hour']}:{tr['start_minute']:02d}",
                'end': f"{tr['end_hour']}:{tr['end_minute']:02d}",
            })
        return timeranges


    def build_creation_rules(self, rule, attributes):
        """
        Return Creation Rules Field
        "creation_rules": [
          {
            "folder_path": "/",
            "host_attributes": {
              "tag_snmp_ds": "no-snmp",
              "tag_agent": "no-agent",
              "tag_piggyback": "piggyback",
              "tag_address_family": "no-ip"
            },
            "delete_hosts": false,
             "host_filters": [
                  "lx1"
                ] }
        ],
        """
        creation_rules = []
        for crule in rule['creation_rules']:
            rule_payload = {
                'folder_path': render_jinja(crule['folder_path'], attributes),
                'delete_hosts': crule['delete_hosts'],
                'host_attributes': dict({x.attribute_name:x.attribute_value \
                                            for x in crule['host_attributes']})
            }
            if crule['host_filters']:
                rule_payload['host_filters'] =  crule['host_filters']
            creation_rules.append(rule_payload)
        return creation_rules



    def build_rule_payload(self, rule, attributes):
        """
        Return Payload as Dict
        """
        try:
            restricted_hosts = rule['restricted_source_hosts']
            creation_rules = self.build_creation_rules(rule, attributes)
            exclude_time_ranges = self.build_timeranges(rule)


            payload =  {
                  "dcd_id": render_jinja(rule['dcd_id'], mode='raise', **attributes),
                  "title": render_jinja(rule['title'], mode='raise', **attributes),
                  "comment": render_jinja(rule['comment'], mode='raise',**attributes),
                  "disabled": rule['disabled'],
                  "site": render_jinja(rule['site'], mode='raise',**attributes),
                  "connector_type": render_jinja(rule['connector_type'], mode='raise',**attributes),
                  "restrict_source_hosts": restricted_hosts,
                  "interval": render_jinja(rule['interval'], mode='raise', **attributes),
                  "creation_rules": creation_rules,
                  "activate_changes_interval": render_jinja(rule['activate_changes_interval'], \
                                                                                    **attributes),
                  "discover_on_creation": rule['discover_on_creation'],
                  "exclude_time_ranges": exclude_time_ranges,
                  "no_deletion_time_after_init": render_jinja(rule['no_deletion_time_after_init'],\
                                                                                    **attributes),
                  "max_cache_age": render_jinja(rule['max_cache_age'], **attributes),
                  "validity_period": render_jinja(rule['validity_period'], **attributes),
            }
            if rule['documentation_url']:
                payload['documentation_url']= rule['documentation_url']
            logger.debug(payload)
            return payload
        except UndefinedError:
            return {}

    def create_rule_in_cmk(self, payload):
        """
        Create not existing rule in checkmk
        """
        self.console(f" * Create Rule {payload['dcd_id']}")
        url = "/domain-types/dcd/collections/all"
        self.request(url, method="POST", data=payload)

    def calculate_rules_of_host(self, hostname, outcomes, attributes):
        """
        Calculate rules for Host
        """
        self.console(f" * Calculate {hostname}")
        for _, rules in outcomes.items():
            for rule in rules:
                rule_payload = self.build_rule_payload(rule, attributes)
        if rule_payload and rule_payload not in self.all_rules:
            self.all_rules.append(rule_payload)

    def export_rules(self):
        """
        Export DCD Rules
        """

        db_objects = Host.objects()
        total = db_objects.count()
        # pylint: disable=too-many-nested-blocks
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print
            task1 = progress.add_task("Calculate Rules", total=total)
            for db_host in Host.objects():
                attributes = self.get_host_attributes(db_host, 'cmk_conf')
                if not attributes:
                    continue
                host_actions = self.actions.get_outcomes(db_host, attributes['all'])
                if host_actions:
                    self.calculate_rules_of_host(db_host.hostname, host_actions, attributes['all'])
                progress.advance(task1)
            task2 = progress.add_task("Send Rules to Checkmk", total=len(self.all_rules))
            count_new = 0
            count_existing = 0
            for rule in self.all_rules:
                if not self.does_rule_exist(rule['dcd_id']):
                    count_new += 1
                    self.create_rule_in_cmk(rule)
                else:
                    count_existing += 1
                progress.advance(task2)

            self.log_details.append(('new_rules', count_new))
            self.log_details.append(('existing_rules', count_existing))
