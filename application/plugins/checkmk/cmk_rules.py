
"""
Export Checkmk Rules
"""
import ast
from pprint import pformat


from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.models.host import Host
from application.plugins.checkmk.cmk2 import CmkException, CMK2
from application.helpers.syncer_jinja import render_jinja, get_list
from application.modules.debug import ColorCodes as CC


def clean_postproccessed(data):
    """
    Normalize Checkmk's explicit_password tuples before rule comparison.
    """
    # Intentional: Checkmk re-encrypts the stored explicit_password tuple
    # (id, password) on every GET, so the ciphertext differs across reads
    # even when the password has not changed. Normalizing that tuple to
    # (None, None) before comparing rules prevents endless "update" churn
    # on every sync. The trade-off — that a real password change is not
    # detected here — is accepted; password rotation is managed by the
    # Checkmk password store, not by rule diffs.
    output = {}
    for key, value in data.items():
        if isinstance(value, tuple):
            if value[0] == 'cmk_postprocessed' and \
                    value[1] == 'explicit_password':
                new_tuple = (None, None)
                new_value = (value[0], value[1], new_tuple)
                value = new_value
        output[key] = value
    return output

def deep_compare(a, b):
    """
    Compare Checkmk rules which are nested with key: [list]
    Without the function, they may not match if the order in the list is diffrent.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        a = clean_postproccessed(a)
        b = clean_postproccessed(b)
        if set(a.keys()) != set(b.keys()):
            return False
        return all(deep_compare(v, b[k]) for k, v in a.items())
    if isinstance(a, list) and isinstance(b, list):
        return sorted(a, key=str) == sorted(b, key=str)
    return a == b


def analyze_value_differences(expected, actual):
    """
    Analyze and describe differences between two values
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences = []
        # Check for different keys
        expected_keys = set(expected.keys())
        actual_keys = set(actual.keys())

        missing_keys = expected_keys - actual_keys
        extra_keys = actual_keys - expected_keys
        common_keys = expected_keys & actual_keys

        if missing_keys:
            differences.append(f"Missing keys: {', '.join(missing_keys)}")
        if extra_keys:
            differences.append(f"Extra keys: {', '.join(extra_keys)}")

        for key in common_keys:
            if expected[key] != actual[key]:
                differences.append(
                    f"Key '{key}': expected {repr(expected[key])}, "
                    f"got {repr(actual[key])}"
                )

        return '; '.join(differences) if differences else "No specific differences found"

    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return f"List length differs: expected {len(expected)}, got {len(actual)}"

        differences = []
        for i, (exp_item, act_item) in enumerate(zip(expected, actual)):
            if exp_item != act_item:
                differences.append(f"Index {i}: expected {repr(exp_item)}, got {repr(act_item)}")

        return '; '.join(differences) if differences else "List order differs"
    return f"Expected: {repr(expected)}, Got: {repr(actual)}"

class CheckmkRuleSync(CMK2):
    """
    Export Checkmk Rules
    """
    rulsets_by_type = {}

    def __init__(self, account=False):
        super().__init__(account)
        # Tri-state etag probe:
        #   None  = not yet probed
        #   False = wildcard If-Match works → skip the pre-GET
        #   True  = wildcard rejected, fall back to GET+PUT for the rest
        #           of this run so we don't retry on every rule
        self._rule_etag_wildcard_rejected = None

    def build_rule_hash(self, rule_template, conditions):
        """
        Create a hash which can identify the rule
        """
        return hash(str(rule_template)+str(conditions))

    def update_rule(self, rule_id, update_payload):
        """
        Update an existing Checkmk rule in place.

        Checkmk requires an ``If-Match`` header on rule updates.
        Instead of always doing a GET to fetch the current ETag
        (one extra round-trip per rule), we first try a wildcard
        ``If-Match: *``. If the endpoint accepts it, we save one
        request per updated rule — roughly halving the traffic in
        the cleanup phase. On the first rejection we cache that
        this run has to fall back to GET+PUT so we don't retry the
        wildcard on every rule.
        """
        rule_url = f'/objects/rule/{rule_id}'

        if self._rule_etag_wildcard_rejected is not True:
            try:
                _, headers = self.request(
                    rule_url, data=update_payload, method="PUT",
                    additional_header={'If-Match': '*'},
                )
            except CmkException:
                self._rule_etag_wildcard_rejected = True
            else:
                if headers.get('status_code') == 200:
                    return
                # Server accepted the request path but rejected the
                # wildcard precondition — remember and fall back.
                self._rule_etag_wildcard_rejected = True

        _, get_headers = self.request(rule_url, method="GET")
        etag = get_headers.get('etag') or get_headers.get('ETag')
        additional = {'If-Match': etag} if etag else None
        self.request(
            rule_url, data=update_payload, method="PUT",
            additional_header=additional,
        )


    # pylint: disable=too-many-locals,too-many-branches
    def build_condition_and_update_rule_params(
        self, rule_params, attributes, loop_value=None, loop_idx=None
    ):
        """
        Build condition_tpl and update rule_params accordingly.
        Uses self.checkmk_version.
        Optionally injects loop_value as 'loop' into the template context.
        """
        # Work on a local copy — the outcome dicts are shared across hosts
        # via the rule-engine's prepared-outcomes cache, so mutating them
        # here (del value_template/condition_* etc.) would break the next
        # host that hits the same rule.
        rule_params = dict(rule_params)

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
        rule_params['optimize'] = False

        # Handle condition_label_template
        has_hostlabel_condition = False
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
            has_hostlabel_condition = True
            del rule_params['condition_label_template']


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

        # Handle condition_host. It's always at the end to calculate correct
        # identification hash of entry
        if rule_params.get('condition_host'):
            host_condition = render_jinja(rule_params['condition_host'], **context)
            owner_hostname = context['HOSTNAME']

            if host_condition:
                if not has_hostlabel_condition and owner_hostname == host_condition:
                    # This rule is for the current Object and there are no other
                    # conditions; hash is built with the condition template which
                    # does not include the hostname condition
                    rule_hash = self.build_rule_hash(rule_params, condition_tpl)
                    rule_params['optimize_rule_hash'] = rule_hash
                    rule_params['optimize'] = True
                condition_tpl["host_name"] = {
                    "match_on": get_list(host_condition),
                    "operator": "one_of"
                }
            del rule_params['condition_host']

        rule_params['condition'] = condition_tpl
        return rule_params

    def optimize_rules(self):
        """
        optimize rules to prevent to many duplicates
        """
        for rule_type, rules in list(self.rulsets_by_type.items()):
            final_rules = []
            host_for_hash = {}
            rule_by_hash = {}
            for rule in rules:
                if rule['optimize']:
                    condition_host = rule['condition']['host_name']['match_on'][0]
                    rule_hash = rule['optimize_rule_hash']
                    host_for_hash.setdefault(rule_hash, [])
                    host_for_hash[rule_hash].append(condition_host)
                    if rule_hash not in rule_by_hash:
                        rule['condition']['host_name']['match_on'] = []
                        rule_by_hash[rule_hash] = rule
                    rule_by_hash[rule_hash]['condition']['host_name']['match_on'].append(
                        condition_host)
                else:
                    # nothing to optimize, so just add
                    final_rules.append(rule)
            final_rules.extend(rule_by_hash.values())
            self.rulsets_by_type[rule_type] = final_rules



    def export_cmk_rules(self):
        """
        Export config rules to checkmk
        """
        print(f"\n{CC.HEADER}Build needed Rules{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")


        object_filter = self.config['settings'].get(self.name, {}).get('filter')
        if not object_filter:
            # Default/ Legacy Behavior
            db_objects = Host.objects()
        else:
            db_objects = Host.objects_by_filter(object_filter)

        total = db_objects.count()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task("Calculate rules", total=total)
            object_filter = self.config['settings'].get(self.name, {}).get('filter')
            for db_host in db_objects:
                attributes = self.get_attributes(db_host, 'checkmk')
                if not attributes:
                    logger.debug("Skipped: %s", db_host.hostname)
                    progress.advance(task1)
                    continue
                # self.actions is injected by the inits.export_rules wiring
                host_actions = self.actions.get_outcomes(  # pylint: disable=no-member
                    db_host, attributes['all'])
                if host_actions:
                    self.calculate_rules_of_host(host_actions, attributes)
                progress.advance(task1)


        self.optimize_rules()
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


    # pylint: disable=too-many-locals,too-many-branches,too-many-statements
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
                    condition_matches = []  # Collect all rules with matching conditions

                    for rule in list(rules):
                        try:
                            cmk_value = ast.literal_eval(rule['value'])
                            check_value = ast.literal_eval(value)
                        except (SyntaxError, KeyError):
                            logger.debug("Invalid Value: '%s' or '%s'", rule['value'], value)
                            continue

                        condition_match = rule['condition'] == cmk_condition
                        value_match = deep_compare(cmk_value, check_value)

                        # Collect all rules with matching conditions
                        if condition_match:
                            condition_matches.append({
                                'rule': rule,
                                'expected_value': cmk_value,
                                'actual_value': check_value,
                                'value_match': value_match
                            })

                        if condition_match and value_match:
                            logger.debug("FULL MATCH")
                            rule_found = True
                            # Remove from list, so that it not will be created in the next step
                            rules.remove(rule)
                            break

                    # If exactly one of our rules has the same condition but a
                    # different value, this is not a stale rule — it's a value
                    # drift we should push to Checkmk in place. Updating via
                    # PUT preserves the rule id and audit history and avoids a
                    # destructive delete+recreate (which briefly removes the
                    # rule from the active policy and churns ids).
                    if not rule_found and len(condition_matches) == 1 and \
                            not condition_matches[0]['value_match']:
                        our_rule = condition_matches[0]['rule']
                        rule_id = cmk_rule['id']
                        update_payload = {
                            "properties": {
                                "disabled": False,
                                "description": f"cmdbsyncer_{self.account_id}",
                                "comment": our_rule['comment'],
                            },
                            "conditions": our_rule['condition'],
                            "value_raw": our_rule['value'],
                        }
                        try:
                            self.update_rule(rule_id, update_payload)
                            print(f"{CC.OKBLUE} *{CC.ENDC} UPDATE Rule in "
                                  f"{ruleset_name} {rule_id}")
                            rules.remove(our_rule)
                            rule_found = True
                            self.log_details.append((
                                "INFO",
                                f"Updated Rule in {ruleset_name} {rule_id}: "
                                f"{our_rule['value']}",
                            ))
                        except CmkException as error:
                            self.log_details.append((
                                "ERROR",
                                f"Could not update Rule {rule_id} in "
                                f"{ruleset_name}: {error}",
                            ))
                            print(f"{CC.FAIL} Update failed: {error} {CC.ENDC}")

                    # Only warn about flapping when there really are multiple
                    # conflicting matches — a single value drift is handled
                    # above via in-place update.
                    deletion_details = ""
                    if not rule_found and len(condition_matches) > 1:
                        logger.warning(
                            "🔄 POTENTIAL FLAPPING RULES detected in %s:", ruleset_name)
                        logger.warning("Condition: %s", pformat(cmk_condition))
                        logger.warning(
                            "Found %d rules with same condition but different values:",
                            len(condition_matches))

                        deletion_details_list = []
                        for i, match in enumerate(condition_matches, 1):
                            if not match['value_match']:
                                value_diff = analyze_value_differences(
                                    match['expected_value'], match['actual_value'])
                                deletion_details_list.append(f"Option {i}: {value_diff}")
                                logger.warning(
                                    "  Option %d - Expected: %s",
                                    i, pformat(match['expected_value']))
                                logger.warning(
                                    "  Option %d - Actual: %s",
                                    i, pformat(match['actual_value']))
                                logger.warning(
                                    "  Option %d - Difference: %s", i, value_diff)

                        deletion_details = (
                            f"🔄 FLAPPING RULE - {len(condition_matches)} possible values: "
                            + "; ".join(deletion_details_list)
                        )

                    if not rule_found: # Not existing any more
                        rule_id = cmk_rule['id']
                        print(f"{CC.OKBLUE} *{CC.ENDC} DELETE Rule in {ruleset_name} {rule_id}")

                        # Show details only for potentially problematic cases
                        if deletion_details:
                            print(f"{CC.WARNING}   {deletion_details}{CC.ENDC}")

                        url = f'/objects/rule/{rule_id}'
                        self.request(url, method="DELETE")

                        # Log with details if it's a potential flapping rule
                        log_entry = f"Deleted Rule in {ruleset_name} {rule_id}"
                        if deletion_details:
                            log_entry += f" - {deletion_details}"
                        self.log_details.append(("INFO", log_entry))
                progress.advance(task1)
