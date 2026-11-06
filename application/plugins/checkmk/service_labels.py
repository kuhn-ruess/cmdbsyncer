"""
Checkmk Service Labels

Rules in the Syncer decide which service of a host gets which label. Which
services a host has, and the labels they carry, comes from the inventory (see
the Inventorize source "Labels per Service"). A Service Pattern hitting none of
them goes to Checkmk as the pattern itself, with the value rendered from the
host. The result is written to the Checkmk ruleset of the service labels, using
the rule sync of the Setup Rules under an ownership marker of its own.

The condition of a rule decides where a label is written. Once written, a host
keeping its rule no longer depends on it: Checkmk reports the label of a rule
like any other, so a condition asking for a missing label stops matching
because of that very rule, and removing it would bring the label back to
missing.
"""
import ast
import re

from application.helpers.syncer_jinja import render_jinja
from application.models.host import Host
from application.plugins.checkmk.cmk_rules import (
    CheckmkRuleSync,
    condition_hosts,
    folder_within_scope,
    normalize_folder,
)
from application.plugins.checkmk.inventorize import PER_SERVICE_LABELS_ATTRIBUTE

SERVICE_LABEL_RULESET = 'service_label_rules'

# What an outcome whose pattern hits makes of a service.
LABEL_SET = 'set'
LABEL_TAKEN = 'taken'
LABEL_NO_NAME = 'no_name'
LABEL_NO_VALUE = 'no_value'


def exact_service_regex(service):
    """
    Regular expression for exactly this service name. Checkmk matches the
    service condition as a regex on the start of the name, so a plain
    ``Port 2.1`` would match ``Port 2.10`` as well.
    """
    return re.sub(r'([.^$*+?{}\[\]\\|()])', r'\\\1', service) + '$'


def checkmk_service_regex(pattern):
    """
    A Service Pattern as service condition. The Syncer searches the pattern in
    the name, Checkmk matches it from the start of the name.
    """
    return pattern if pattern.startswith('^') else f'.*(?:{pattern})'


def pattern_error(pattern):
    """
    What is wrong with a Service Pattern, empty if nothing is.
    """
    try:
        re.compile(pattern)
    except re.error as error:
        return str(error)
    return ''


def join_earlier_rule(rules, folder, labels, regex):
    """
    Add a regex to the rule in ``rules`` with the same folder and labels. That
    moves it up past the rules in between, which only stays the same if none of
    them sets one of its labels to another value: an overlap would then change
    the value that wins. Otherwise it gets a rule of its own at the end.
    """
    for earlier_folder, earlier_labels, regexes in reversed(rules):
        if earlier_folder != folder:
            continue
        if earlier_labels == labels:
            regexes.append(regex)
            return
        if any(earlier_labels.get(name, value) != value for name, value in labels.items()):
            break
    rules.append((folder, labels, [regex]))


class CheckmkServiceLabelSync(CheckmkRuleSync):
    """
    Export the Service Label rules
    """

    def __init__(self, account=False, probe_version=True):
        super().__init__(account, probe_version)
        self.labels_in_checkmk = {}
        self.every_outcome = []
        self.template_error = ''

    @property
    def rule_marker(self):
        """
        Marker of its own: the Setup Rule export and this one work on the same
        ruleset without seeing each other's rules as their own to clean up.
        """
        return f"cmdbsyncer_{self.account_id}_service_labels"

    def _export_hosts(self):
        """
        Only what the host export sends to Checkmk has services there. Objects
        don't, unless the setting ``filter`` of the account names them.
        """
        return Host.objects_by_filter(self._object_filter())

    def _render(self, template, context, hostname):
        """
        Render a template of a rule. One broken value must not end the run,
        the other services and hosts still get theirs.
        """
        try:
            return render_jinja(template, _ctx=context)
        except Exception as error:  # pylint: disable=broad-exception-caught
            self.template_error = str(error)
            self.log_error(f"{hostname}, {context.get('SERVICE')}: "
                           f"Template '{template}' failed: {error}")
            return ""

    def _hit(self, outcome, service):
        """
        The match of the Service Pattern on the service.
        """
        try:
            return re.search(outcome['service_pattern'], service)
        except re.error as error:
            self.log_error(f"Service Pattern '{outcome['service_pattern']}': {error}")
            return None

    def _step(self, outcome, context, found):
        """
        What one outcome makes of its label in this context. ``found`` holds
        the labels already set, a label in it stays with the earlier outcome.
        """
        hostname = context.get('HOSTNAME')
        step = {'outcome': outcome, 'state': LABEL_NO_NAME}
        step['name'] = self._render(outcome['label_name'], context, hostname)
        if step['name']:
            if step['name'] in found:
                step['state'] = LABEL_TAKEN
            else:
                step['value'] = self._render(outcome['label_value'], context, hostname)
                step['state'] = LABEL_NO_VALUE
                if step['value']:
                    folder = self._render(outcome.get('folder') or '/', context, hostname)
                    step['folder'] = normalize_folder(folder or '/')
                    step['state'] = LABEL_SET
                    found.add(step['name'])
        return step

    def steps_of_service(self, entry, outcomes, attributes):
        """
        What each outcome whose pattern hits makes of one service, in order.

        Per label the first non empty value wins, the way Checkmk treats its
        own rules. So a special case is a rule in front of the general one,
        and an empty value leaves the label to the next rule.
        """
        service = entry['service']
        labels = entry.get('labels') or {}
        found = set()
        for outcome in outcomes:
            hit = self._hit(outcome, service)
            if not hit:
                continue
            context = {
                **attributes,
                'SERVICE': service,
                'MATCH': [hit.group(0)] + [group or '' for group in hit.groups()],
                'LABELS': labels,
            }
            yield self._step(outcome, context, found)

    def steps_of_patterns(self, outcomes, attributes):
        """
        What each outcome whose pattern hits no known service makes of its
        label: rendered from the host, with SERVICE, MATCH and LABELS empty.
        """
        entries = attributes.get(PER_SERVICE_LABELS_ATTRIBUTE) or []
        known = {outcome['service_pattern'] for outcome in outcomes
                 if any(self._hit(outcome, entry['service']) for entry in entries)}
        context = {**attributes, 'SERVICE': '', 'MATCH': [], 'LABELS': {}}
        found = {}
        for outcome in outcomes:
            pattern = outcome['service_pattern']
            if pattern not in known:
                yield self._step(outcome, context, found.setdefault(pattern, set()))

    def labels_of_service(self, entry, outcomes, attributes):
        """
        What the outcomes set on one service, as ``{label: (value, folder)}``.
        """
        return {step['name']: (step['value'], step['folder'])
                for step in self.steps_of_service(entry, outcomes, attributes)
                if step['state'] == LABEL_SET}

    def read_labels_in_checkmk(self):
        """
        What our rules in Checkmk set now, per host and service regex. A
        failed read ends the run: without it no rule could be told to stay.
        """
        url = f"domain-types/rule/collections/all?ruleset_name={SERVICE_LABEL_RULESET}"
        self.labels_in_checkmk = {}
        for cmk_rule in self.request(url, method="GET")[0]['value']:
            if not self._owns_rule(cmk_rule):
                continue
            extensions = cmk_rule['extensions']
            conditions = extensions['conditions']
            labels = ast.literal_eval(extensions['value_raw'])
            services = conditions.get('service_description', {}).get('match_on', [])
            for hostname in condition_hosts(conditions):
                for regex in services:
                    self.labels_in_checkmk.setdefault((hostname, regex), {}).update(labels)

    def kept_labels(self, entry, attributes):
        """
        The labels of a service staying as they are, as ``{label: (value, folder)}``:
        Checkmk has them from us and an enabled rule still renders that value.
        Neither a changed value nor a label no rule renders any more stays.
        """
        key = (attributes.get('HOSTNAME'), exact_service_regex(entry['service']))
        in_checkmk = self.labels_in_checkmk.get(key)
        if not in_checkmk:
            return {}
        kept = {}
        for outcome in self.every_outcome:
            rendered = self.labels_of_service(entry, [outcome], attributes)
            for name, (value, folder) in rendered.items():
                if in_checkmk.get(name) == value:
                    kept.setdefault(name, (value, folder))
        return kept

    def rules_of_host(self, outcomes, attributes):
        """
        The Checkmk rules of one host: services ending up with the same labels
        share a rule. Labels of one service in different folders can't.
        """
        groups = {}
        for entry in attributes.get(PER_SERVICE_LABELS_ATTRIBUTE) or []:
            by_folder = {}
            found = {**self.kept_labels(entry, attributes),
                     **self.labels_of_service(entry, outcomes, attributes)}
            for name, (value, folder) in found.items():
                by_folder.setdefault(folder, {})[name] = value
            for folder, labels in by_folder.items():
                # Fixed key order: the value is compared and shown as text.
                value = repr(dict(sorted(labels.items())))
                groups.setdefault((folder, value), []).append(entry['service'])
        rules = [(folder, value, sorted(exact_service_regex(service) for service in services))
                 for (folder, value), services in sorted(groups.items())]
        rules += self._rules_of_patterns(outcomes, attributes)
        return [self._build_rule(attributes['HOSTNAME'], folder, value, match_on)
                for folder, value, match_on in rules
                if folder_within_scope(folder, self.config.get('limit_by_folders'))]

    def _rules_of_patterns(self, outcomes, attributes):
        """
        The rules of the patterns hitting no known service, in the order of the
        outcomes: unlike the rule of a known service they can overlap, and in
        Checkmk the first rule wins. Patterns with the same labels share a rule.
        """
        groups = {}
        for step in self.steps_of_patterns(outcomes, attributes):
            pattern = step['outcome']['service_pattern']
            error = pattern_error(pattern)
            if error:
                self.log_error(f"Service Pattern '{pattern}': {error}")
            elif step['state'] == LABEL_SET:
                groups.setdefault((step['folder'], pattern), {})[step['name']] = step['value']
        merged = []
        for (folder, pattern), labels in groups.items():
            join_earlier_rule(merged, folder, labels, checkmk_service_regex(pattern))
        return [(folder, repr(dict(sorted(labels.items()))), sorted(regexes))
                for folder, labels, regexes in merged]

    def _build_rule(self, hostname, folder, value, match_on):
        """
        One rule in the shape the rule sync works with. ``optimize`` lets
        hosts with the very same services and value share the rule.
        """
        condition = self._condition_template()
        condition['service_description'] = {
            'match_on': match_on,
            'operator': 'one_of',
        }
        rule_hash = self.build_rule_hash(
            (folder, value), condition['service_description'])
        condition['host_name'] = {'match_on': [hostname], 'operator': 'one_of'}
        return {
            'folder': folder,
            'comment': '',
            'description': self.rule_marker,
            'condition': condition,
            'value': value,
            # A label no longer set has to leave the Checkmk rule as well.
            'enforce_value': True,
            'optimize': True,
            'optimize_rule_hash': rule_hash,
        }

    def calculate_rules(self, use_cache=True):
        """
        The ruleset is always part of the run: without any rule left, the
        cleanup still has to remove ours.
        """
        self.rulsets_by_type.setdefault(SERVICE_LABEL_RULESET, [])
        self.read_labels_in_checkmk()
        # The outcomes of all enabled rules, whatever their conditions say.
        self.every_outcome = [dict(outcome) for rule in self.actions.rules  # pylint: disable=no-member
                              for outcome in rule.to_mongo().get('outcomes', [])]
        super().calculate_rules(use_cache)

    def _calculate_host(self, db_host, host_actions, attributes):
        """
        Every host goes through its rules, as one no condition matches can
        have rules to keep. Only then HOST_FOLDER is known for the outcomes.
        """
        host_attributes = self._with_host_folder(
            db_host, {'default': self.every_outcome}, attributes)
        self.calculate_rules_of_host(host_actions or {'default': []}, host_attributes)

    def calculate_rules_of_host(self, host_actions, attributes):
        """
        Calculate the rules of one host from its rule outcomes
        """
        for rule in self.rules_of_host(host_actions['default'], attributes['all']):
            self._collect_rule(SERVICE_LABEL_RULESET, rule)

    def _debug_row(self, target, step):
        """
        One row of the host debug page, if there is one: what the export sends,
        or the error text of a failed template as the value.
        """
        error, self.template_error = self.template_error, ''
        if not error and step['state'] != LABEL_SET:
            return None
        return {'service': target, 'name': step['name'], 'value': error or step['value']}

    def debug_host(self, outcomes, db_host, attributes):
        """
        The rule debug of the host debug page: what the outcomes of the rules
        matching this host send to Checkmk, through the walk of the export. A
        regex with known services gets one row per service and label, any other
        one row per label under the regex itself. An object gets no row, as the
        export leaves it out.
        """
        if db_host.is_object:
            return []
        host_attributes = self._with_host_folder(
            db_host, {'default': outcomes}, attributes)['all']
        rows = {outcome['service_pattern']: [] for outcome in outcomes}
        for entry in host_attributes.get(PER_SERVICE_LABELS_ATTRIBUTE) or []:
            for step in self.steps_of_service(entry, outcomes, host_attributes):
                rows[step['outcome']['service_pattern']].append(
                    self._debug_row(entry['service'], step))
        for step in self.steps_of_patterns(outcomes, host_attributes):
            pattern = step['outcome']['service_pattern']
            self.template_error = self.template_error or pattern_error(pattern)
            rows[pattern].append(self._debug_row(pattern, step))
        return [row for pattern_rows in rows.values() for row in pattern_rows if row]
