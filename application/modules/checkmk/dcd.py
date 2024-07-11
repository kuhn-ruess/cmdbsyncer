"""
Checkmk DCD Manager
"""

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application.modules.checkmk.config_sync import SyncConfiguration
from application.modules.checkmk.models import CheckmkDCDRule


class CheckmkDCDRuleSync(SyncConfiguration):
    """
    Sync Checkmk Downtimes
    """
    console = None


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
        for tr in rule.exclude_time_ranges:
            timeranges.append({
                'start': f"{tr['start_hour']}:{tr['start_minute']:02d}",
                'end': f"{tr['end_hour']}:{tr['end_minute']:02d}",
            })
        return timeranges


    def build_creation_rules(self, rule):
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
            "delete_hosts": false
          }
        ],
        """
        creation_rules = []
        for crule in rule.creation_rules:
            creation_rules.append({
                'folder_path': crule['folder_path'],
                'host_attributes': dict({x.attribute_name:x.attribute_value \
                                            for x in crule.host_attributes})
            })
        return creation_rules



    def build_rule_payload(self, rule):
        """
        Return Payload as Dict
        """
        restricted_hosts = rule.restricted_source_hosts
        creation_rules = self.build_creation_rules(rule)
        exclude_time_ranges = self.build_timeranges(rule)


        return {
              "dcd_id": rule['dcd_id'],
              "title": rule['title'],
              "comment": rule['comment'],
              #"documentation_url": rule['documentation_url'],
              "disabled": rule['disabled'],
              "site": rule['site'],
              "connector_type": rule['connector_type'],
              "restrict_source_hosts": restricted_hosts,
              "interval": rule['interval'],
              "creation_rules": creation_rules,
              "activate_changes_interval": rule['activate_changes_interval'],
              "discover_on_creation": rule['discover_on_creation'],
              "exclude_time_ranges": exclude_time_ranges,
              "no_deletion_time_after_init": rule['no_deletion_time_after_init'],
              "max_cache_age": rule['max_cache_age'],
              "validity_period": rule['validity_period'],
        }

    def create_rule(self, rule):
        """
        Create not existing rule in checkmk
        """
        self.console(f" * Create Rule {rule['dcd_id']}")
        url = "/domain-types/dcd/collections/all"
        payload = self.build_rule_payload(rule)
        self.request(url, method="POST", data=payload)

    def export_rules(self):
        """
        Export DCD Rules
        """
        # Collect Rules
        total = CheckmkDCDRule.objects(enabled=True).count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            self.console = progress.console.print

            task1 = progress.add_task("Export DCD Rules", total=total)
            for rule in CheckmkDCDRule.objects(enabled=True):
                if self.does_rule_exist(rule.dcd_id):
                    self.console(f' * Rule {rule.dcd_id} already exists')
                    progress.advance(task1)
                    continue
                self.create_rule(rule)
                progress.advance(task1)
