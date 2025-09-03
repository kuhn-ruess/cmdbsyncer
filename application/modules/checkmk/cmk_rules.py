#!/usr/bin/env python3
"""
Export Checkmk Rules
"""
#pylint: disable=logging-fstring-interpolation
import ast
from pprint import pformat


from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.models.host import Host
from application.modules.checkmk.cmk2 import CmkException, CMK2
from application.helpers.syncer_jinja import render_jinja, get_list
from application.modules.debug import ColorCodes as CC

def deep_compare(a, b):
    """
    Compare Checkmk rules which are nested with key: [list] 
    Without the function, they may not match if the order in the list is diffrent.
    @TODO Check for Side effects like not longer detected rules
    """
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(deep_compare(a[k], b[k]) for k in a)
    elif isinstance(a, list) and isinstance(b, list):
        return sorted(a, key=lambda x: str(x)) == sorted(b, key=lambda x: str(x))
    else:
        return a == b

class CheckmkRuleSync(CMK2):
    """
    Export Checkmk Rules
    """
    rulsets_by_type = {}

    def build_condition_and_update_rule_params(
        self, rule_params, attributes, loop_value=None, loop_idx=None
    ):
        """
        Build condition_tpl and update rule_params accordingly.
        Uses self.checkmk_version.
        Optionally injects loop_value as 'loop' into the template context.
        """
        # Setup condition template based on Checkmk version
        if self.checkmk_version.startswith('2.2'):
            condition_tpl = {"host_tags": [], "service_labels": []}
        else:
            condition_tpl = {"host_tags": [], "service_label_groups": [],
                             "host_label_groups": []}

        # Prepare context for Jinja rendering
        context = dict(attributes['all'])
        if loop_value is not None:
            context['loop'] = loop_value
            context['loop_idx'] = loop_idx

        # Render value and folder
        value = render_jinja(rule_params['value_template'], **context)
        rule_params['folder'] = render_jinja(rule_params['folder'], **context)
        rule_params['value'] = value
        del rule_params['value_template']

        # Handle condition_label_template
        if rule_params.get('condition_label_template'):
            label_condition = render_jinja(rule_params['condition_label_template'], **context)
            label_key, label_value = label_condition.split(':')
            if not label_key or not label_value:
                return None  # skip this rule
            if self.checkmk_version.startswith('2.2'):
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

        # Handle condition_host
        if rule_params.get('condition_host'):
            host_condition = render_jinja(rule_params['condition_host'], **context)
            if host_condition:
                condition_tpl["host_name"] = {
                    "match_on": get_list(host_condition),
                    "operator": "one_of"
                }
            del rule_params['condition_host']

        # Handle condition_service (legacy support)
        if 'condition_service' in rule_params:
            if rule_params['condition_service']:
                service_condition = render_jinja(rule_params['condition_service'], **context)
                condition_tpl['service_description'] = {
                    "match_on": get_list(service_condition),
                    "operator": "one_of"
                }
            del rule_params['condition_service']

        if 'condition_service_label' in rule_params:
            if rule_params['condition_service_label']:
                service_label_condition = \
                    render_jinja(rule_params['condition_service_label'], **context)
                condition_tpl['service_label_groups'] = [{
                    "label_group": [
                        {"operator": "and", "label": x}
                        for x in get_list(service_label_condition)
                    ],
                    "operator": "and"
                }]
            del rule_params['condition_service_label']


        rule_params['condition'] = condition_tpl
        return rule_params

    def export_cmk_rules(self): # pylint: disable=too-many-branches, too-many-statements
        """
        Export config rules to checkmk
        """
        print(f"\n{CC.HEADER}Build needed Rules{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")


        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        db_objects = Host.objects_by_filter(object_filter)

        total = db_objects.count()
        # pylint: disable=too-many-nested-blocks
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Calculate rules", total=total)
            object_filter = self.config['settings'].get(self.name, {}).get('filter')
            for db_host in db_objects:
                attributes = self.get_attributes(db_host, 'checkmk')
                if not attributes:
                    logger.debug(f"Skipped: {db_host.hostname}")
                    progress.advance(task1)
                    continue
                host_actions = self.actions.get_outcomes(db_host, attributes['all'])
                if host_actions:
                    self.calculate_rules_of_host(host_actions, attributes)
                progress.advance(task1)

        self.clean_rules()
        self.create_rules()


    def calculate_rules_of_host(self, host_actions, attributes):
        """
        Calculate rules by Attribute of Host
        """
        for rule_type, rules in host_actions.items():
            for rule_params in rules:
                if rule_params.get('loop_over_list'):
                    loop_list = get_list(attributes['all'][rule_params['list_to_loop']])
                    for loop_idx, loop_value in enumerate(loop_list):
                        loop_rule_params = dict(rule_params)
                        loop_rule_params.pop('loop_over_list', None)
                        loop_rule_params.pop('list_to_loop', None)
                        updated_rule = self.build_condition_and_update_rule_params(
                            loop_rule_params, attributes, loop_value, loop_idx
                        )
                        if updated_rule is None:
                            continue
                        self.rulsets_by_type.setdefault(rule_type, [])
                        if updated_rule not in self.rulsets_by_type[rule_type]:
                            self.rulsets_by_type[rule_type].append(updated_rule)
                else:
                    updated_rule = self.build_condition_and_update_rule_params(
                        rule_params, attributes
                    )
                    if updated_rule is None:
                        continue
                    self.rulsets_by_type.setdefault(rule_type, [])
                    if updated_rule not in self.rulsets_by_type[rule_type]:
                        self.rulsets_by_type[rule_type].append(updated_rule)



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

                        condition_match = rule['condition'] == cmk_condition


                        value_match = deep_compare(cmk_value, check_value)

                        if not condition_match:
                            logger.debug("NO MATCH FOR CONDITION")
                            logger.debug(f"Checkmk Condition: {pformat(cmk_condition)}")
                            logger.debug(f"Syncer Condition: {pformat(rule['condition'])}")
                        if not value_match:
                            logger.debug("NO MATCH ON VALUE")
                            logger.debug(f"Checkmk Value: {pformat(cmk_value)}")
                            logger.debug(f"Syncer Value: {pformat(check_value)}")

                        if condition_match and value_match:
                            logger.debug("FULL MATCH")
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
