#!/usr/bin/env python3
"""
Export Checkmk Rules
"""
#pylint: disable=logging-fstring-interpolation
import ast


from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.models.host import Host
from application.modules.checkmk.cmk2 import CmkException, CMK2
from application.helpers.syncer_jinja import render_jinja
from application.modules.debug import ColorCodes as CC

from syncerapi.v1.core import (
    app_config,
)

class CheckmkRuleSync(CMK2):
    """
    Export Checkmk Rules
    """
    rulsets_by_type = {}

    name = "Synced Configuration Rules"
    source = "cmk_rule_sync"

    def export_cmk_rules(self): # pylint: disable=too-many-branches, too-many-statements
        """
        Export config rules to checkmk
        """
        print(f"\n{CC.HEADER}Build needed Rules{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")


        db_objects = Host.objects()
        total = db_objects.count()
        # pylint: disable=too-many-nested-blocks
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Calculate Ruels", total=total)
            for db_host in Host.objects():
                attributes = self.get_host_attributes(db_host, 'cmk_conf')
                if not attributes:
                    continue
                host_actions = self.actions.get_outcomes(db_host, attributes['all'])
                if host_actions:
                    self.calculate_rules_of_host(db_host.hostname, host_actions, attributes)
                progress.advance(task1)

        self.clean_rules()
        self.create_rules()


    def calculate_rules_of_host(self, hostname, host_actions, attributes):
        """
        Calculate rules by Attribute of Host
        """
        for rule_type, rules in host_actions.items():
            for rule_params in rules:
                # Render Template Value
                if app_config['CMK_SUPPORT'] == '2.2':
                    condition_tpl = {"host_tags": [], "service_labels": []}
                else:
                    condition_tpl = {"host_tags": [], "service_label_groups": [],
                                     "host_label_groups": []}
                value = \
                    render_jinja(rule_params['value_template'],
                                 HOSTNAME=hostname, **attributes['all'])

                rule_params['folder'] =\
                    render_jinja(rule_params['folder'],
                                 HOSTNAME=hostname, **attributes['all'])

                # Overwrite the Params again
                rule_params['value'] = value
                del rule_params['value_template']

                if rule_params['condition_label_template']:
                    label_condition = \
                        render_jinja(rule_params['condition_label_template'],
                                     HOSTNAME=hostname,
                                     **attributes['all'])

                    label_key, label_value = label_condition.split(':')
                    # Fix bug in case of empty Labels in store
                    if not label_key or not label_value:
                        continue
                    if app_config['CMK_SUPPORT'] == '2.2':
                        condition_tpl['host_labels'] = [{
                                                "key": label_key,
                                                "operator": "is",
                                                "value": label_value
                                             }]
                    else:
                        condition_tpl['host_label_groups'] = [{
                                                "operator": "and",
                                                    "label_group": [{
                                                        "operator": "and",
                                                        "label": f"{label_key}:{label_value}",
                                                        }],
                                                    }]
                del rule_params['condition_label_template']

                if rule_params['condition_host']:
                    host_condition = \
                        render_jinja(rule_params['condition_host'],
                                     HOSTNAME=hostname,
                                     **attributes['all'])
                    if host_condition:
                        condition_tpl["host_name"]= {
                                        "match_on": host_condition.split(','),
                                        "operator": "one_of"
                                      }

                del rule_params['condition_host']


                rule_params['condition'] = condition_tpl

                self.rulsets_by_type.setdefault(rule_type, [])
                if rule_params not in self.rulsets_by_type[rule_type]:
                    self.rulsets_by_type[rule_type].append(rule_params)



    def create_rules(self):
        """
        Create needed Rules in Checkmk
        """
        print(f"{CC.OKGREEN} -- {CC.ENDC} Create new Rules")
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:

            task1 = progress.add_task("Create Rules", total=len(self.rulsets_by_type))
            for ruleset_name, rules in self.rulsets_by_type.items():
                for rule in rules:
                    template = {
                        "ruleset": f"{ruleset_name}",
                        "folder": rule['folder'],
                        "properties": {
                            "disabled": False,
                            "description": f"cmdbsyncer_{self.account_id}",
                            "comment": rule['comment'],
                        },
                        'conditions' : rule['condition'],
                        'value_raw' : rule['value'],
                    }


                    print(f"{CC.OKBLUE} *{CC.ENDC} Create Rule in {ruleset_name} " \
                          f"({rule['condition']})")
                    url = "domain-types/rule/collections/all"
                    try:
                        self.request(url, data=template, method="POST")
                        self.log_details.append(("INFO",
                                              f"Created Rule in {ruleset_name}: {rule['value']}"))
                    except CmkException as error:
                        self.log_details.append(("ERROR",
                                             "Could not create Rules: "\
                                             f"{template}, Response: {error}"))
                        print(f"{CC.FAIL} Failue: {error} {CC.ENDC}")
                progress.advance(task1)


    def clean_rules(self):
        """
        Clean not longer needed Rules from Checkmk
        """
        print(f"{CC.OKGREEN} -- {CC.ENDC} Clean existing CMK configuration")
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:

            task1 = progress.add_task("Cleanup Rules", total=len(self.rulsets_by_type))
            for ruleset_name, rules in self.rulsets_by_type.items():
                url = f"domain-types/rule/collections/all?ruleset_name={ruleset_name}"
                rule_response = self.request(url, method="GET")[0]
                for cmk_rule in rule_response['value']:
                    if cmk_rule['extensions']['properties'].get('description', '') != \
                        f'cmdbsyncer_{self.account_id}':
                        continue



                    value = cmk_rule['extensions']['value_raw']
                    cmk_condition = cmk_rule['extensions']['conditions']
                    rule_found = False
                    for rule in rules:
                        try:
                            cmk_value = ast.literal_eval(rule['value'])
                            check_value = ast.literal_eval(value)
                        except (SyntaxError, KeyError):
                            logger.debug(f"Invalid Value: '{rule['value']}' or '{value}'")
                            continue

                        if rule['condition'] == cmk_condition and cmk_value == check_value:
                            rule_found = True
                            # Remove from list, so that it not will be created in the next step
                            # pylint: disable=unnecessary-dict-index-lookup
                            self.rulsets_by_type[ruleset_name].remove(rule)

                    if not rule_found: # Not existing any more
                        rule_id = cmk_rule['id']
                        print(f"{CC.OKBLUE} *{CC.ENDC} DELETE Rule in {ruleset_name} {rule_id}")
                        url = f'/objects/rule/{rule_id}'
                        self.request(url, method="DELETE")
                        self.log_details.append(("INFO",
                                                 f"Deleted Rule in {ruleset_name} {rule_id}"))
                progress.advance(task1)
