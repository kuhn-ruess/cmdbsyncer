"""
Checkmk Notification Rules Export

Targets the Checkmk 2.4 / 2.5 REST API. The rule body schema is
**dense**: every condition / contact-selection slot must be present,
disabled ones as ``{"state": "disabled"}``. The event-type values use
the API's lowercase flag names with every flag spelled out (``False``
by default, ``True`` for selected ones).
"""
import ast
import json

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.models.host import Host
from application.modules.rule.rule import Rule
from application.plugins.checkmk.cmk2 import CMK2, CmkException
from application.plugins.checkmk.cmk_rules import deep_compare
from application.helpers.syncer_jinja import render_jinja, get_list, check_jinja_syntax
from application.modules.debug import ColorCodes as CC


# The plug-ins Checkmk ships with. It validates their parameters against
# a schema of its own, so a rule naming one of them is pushed with the
# "following parameters" option and Checkmk keeps owning the parameter
# set. Anything else is a script in the site's notifications directory
# and has to go out as a custom plug-in — see BUILTIN_PLUGIN_OPTION
# below. Identical list on Checkmk 2.4 and 2.5.
NOTIFICATION_METHOD_SUGGESTIONS = [
    'mail', 'asciimail',
    'cisco_webex_teams', 'ilert', 'jira_issues', 'jsm_operations',
    'mkeventd', 'msteams', 'opsgenie_issues', 'pagerduty', 'pushover',
    'servicenow', 'signl4', 'slack', 'sms', 'sms_api', 'spectrum',
    'victorops',
]

BUILTIN_NOTIFICATION_PLUGINS = frozenset(NOTIFICATION_METHOD_SUGGESTIONS)

# Checkmk takes a built-in plug-in and a third-party script through two
# different options of the same field. Sending a script name under the
# built-in option is rejected with "Unsupported value: <name>"; the
# custom option takes the parameter list the script is called with and
# requires the script to exist in the site.
BUILTIN_PLUGIN_OPTION = 'create_notification_with_the_following_parameters'
CUSTOM_PLUGIN_OPTION = 'create_notification_with_custom_parameters'

# (api_flag, human_readable_label) — values are exactly the keys
# Checkmk's REST API uses inside match_host_event_type.value /
# match_service_event_type.value. The full set is required in every
# rule_config, so values stored here also drive the dense default
# skeleton built in `_event_dict`.
HOST_EVENT_TYPE_CHOICES = [
    ('up_down',                          'Host: UP → DOWN'),
    ('up_unreachable',                   'Host: UP → UNREACHABLE'),
    ('down_up',                          'Host: DOWN → UP'),
    ('down_unreachable',                 'Host: DOWN → UNREACHABLE'),
    ('unreachable_down',                 'Host: UNREACHABLE → DOWN'),
    ('unreachable_up',                   'Host: UNREACHABLE → UP'),
    ('any_up',                           'Host: any → UP'),
    ('any_down',                         'Host: any → DOWN'),
    ('any_unreachable',                  'Host: any → UNREACHABLE'),
    ('start_or_end_of_flapping_state',   'Start / end of flapping state'),
    ('start_or_end_of_scheduled_downtime', 'Start / end of scheduled downtime'),
    ('acknowledgement_of_problem',       'Acknowledgement of problem'),
    ('alert_handler_execution_successful', 'Alert handler executed (OK)'),
    ('alert_handler_execution_failed',   'Alert handler executed (failed)'),
]

SERVICE_EVENT_TYPE_CHOICES = [
    ('ok_warn',     'Service: OK → WARN'),
    ('ok_ok',       'Service: OK → OK'),
    ('ok_crit',     'Service: OK → CRIT'),
    ('ok_unknown',  'Service: OK → UNKNOWN'),
    ('warn_ok',     'Service: WARN → OK'),
    ('warn_crit',   'Service: WARN → CRIT'),
    ('warn_unknown','Service: WARN → UNKNOWN'),
    ('crit_ok',     'Service: CRIT → OK'),
    ('crit_warn',   'Service: CRIT → WARN'),
    ('crit_unknown','Service: CRIT → UNKNOWN'),
    ('unknown_ok',  'Service: UNKNOWN → OK'),
    ('unknown_warn','Service: UNKNOWN → WARN'),
    ('unknown_crit','Service: UNKNOWN → CRIT'),
    ('any_ok',      'Service: any → OK'),
    ('any_warn',    'Service: any → WARN'),
    ('any_crit',    'Service: any → CRIT'),
    ('any_unknown', 'Service: any → UNKNOWN'),
    ('start_or_end_of_flapping_state',   'Start / end of flapping state'),
    ('start_or_end_of_scheduled_downtime', 'Start / end of scheduled downtime'),
    ('acknowledgement_of_problem',       'Acknowledgement of problem'),
    ('alert_handler_execution_successful', 'Alert handler executed (OK)'),
    ('alert_handler_execution_failed',   'Alert handler executed (failed)'),
]

HOST_EVENT_FLAGS = [flag for flag, _label in HOST_EVENT_TYPE_CHOICES]
SERVICE_EVENT_FLAGS = [flag for flag, _label in SERVICE_EVENT_TYPE_CHOICES]

# The full default skeletons CMK 2.4/2.5 expects — every key present
# with state=disabled. We selectively flip a few of these to enabled
# in `_build_rule_config` based on what the admin filled in.
CONTACT_SELECTION_KEYS = [
    'all_contacts_of_the_notified_object',
    'all_users',
    'all_users_with_an_email_address',
    'the_following_users',
    'members_of_contact_groups',
    'explicit_email_addresses',
    'restrict_by_custom_macros',
    'restrict_by_contact_groups',
]
CONDITION_KEYS = [
    'match_sites', 'match_folder', 'match_host_tags', 'match_host_labels',
    'match_host_groups', 'match_hosts', 'match_exclude_hosts',
    'match_service_labels', 'match_service_groups',
    'match_exclude_service_groups', 'match_service_groups_regex',
    'match_exclude_service_groups_regex', 'match_services',
    'match_exclude_services', 'match_check_types', 'match_plugin_output',
    'match_contact_groups', 'match_service_levels',
    'match_only_during_time_period', 'match_host_event_type',
    'match_service_event_type', 'restrict_to_notification_numbers',
    'throttle_periodic_notifications', 'match_notification_comment',
    'event_console_alerts',
]


class NotificationRuleAction(Rule):
    """Collects matching ``CheckmkNotificationRule`` outcomes for one host."""
    name = "Checkmk -> Notification Rules"

    def add_outcomes(self, _rule, rule_outcomes, outcomes):
        outcomes.setdefault('rules', [])
        for outcome in rule_outcomes:
            outcomes['rules'].append(outcome)
        return outcomes


# Outcome fields rendered as Jinja against the host's attributes. The
# export walks them to build the rule conditions; the template check
# walks the same list, so a new field cannot be forgotten in one place.
MATCH_FIELDS = (
    'match_contact_groups',
    'match_host_groups',
    'match_service_groups',
    'match_sites',
    'match_folder',
    'match_hosts',
    'match_exclude_hosts',
    'match_services',
    'match_exclude_services',
    'match_host_labels',
    'match_service_labels',
    'match_host_tags',
    'match_check_types',
    'match_plugin_output',
    'match_only_during_time_period',
    'match_service_levels',
    'match_contacts',
)

JINJA_FIELDS = ('multiply_list', 'notification_parameters',
                'contact_group_recipients') + MATCH_FIELDS


def _field_value(outcome, field):
    """Read one outcome field — an outcome is a dict during the export
    and an embedded document when it comes straight from the rule."""
    if isinstance(outcome, dict):
        return outcome.get(field)
    return getattr(outcome, field, None)


def validate_outcome_jinja(outcome):
    """
    Check every template field of one outcome for Jinja syntax errors.

    Broken Jinja renders to an empty string, and an outcome without
    recipients is dropped — so a single typo costs the whole rule with
    nothing to look at afterwards. Returns ``[(field, message), …]``,
    empty when everything compiles.
    """
    errors = []
    for field in JINJA_FIELDS:
        if defect := check_jinja_syntax(_field_value(outcome, field)):
            errors.append((field, defect))
    return errors


# Placeholder for the secret of a password that has to be filled in.
# Kept out of the syncer database itself — the account is where a
# secret belongs, and an external secret store is honoured there.
PASSWORD_PLACEHOLDER = '{{ACCOUNT:<account>:password}}'


def _is_password_value(value):
    """Whether a configuration value is one of its password fields."""
    return (isinstance(value, list) and len(value) == 4
            and value[0] in ('explicit_password', 'stored_password'))


def _password_template(value):
    """
    The password shape the notification rule endpoint wants, keeping
    whatever can be kept.

    A configuration hands its password out the way its own mask posts
    it back — ``["explicit_password", <id>, <secret>, <encrypted>]`` —
    and the secret of an existing one arrives encrypted on top. That
    shape is rejected by the rule endpoint with "No password provided",
    so it is rewritten; the id survives, because a rule lands on an
    existing configuration only by repeating its parameters exactly. A
    password taken from the Checkmk password store carries no secret at
    all and can therefore be repeated as it is.
    """
    ident = value[1] if isinstance(value[1], str) else ''
    if value[0] == 'stored_password':
        return ['cmk_postprocessed', 'stored_password', [ident, '']]
    return ['cmk_postprocessed', 'explicit_password',
            [ident, PASSWORD_PLACEHOLDER]]


def _with_password_template(params):
    """Rewrite every password field of a parameter set."""
    return {key: (_password_template(value) if _is_password_value(value) else value)
            for key, value in params.items()}


def parameter_template(form_spec):
    """
    Skeleton of the parameters a plug-in declares, taken from the
    ``form_spec`` collection Checkmk serves for it.

    Checkmk answers a missing parameter with "A required (sub-)field is
    missing." without ever naming it, so offering the fields beats
    guessing them.
    """
    defaults = (((form_spec or {}).get('extensions', {}) or {})
                .get('default_values', {}) or {})
    return _with_password_template(
        (defaults.get('parameter_properties', {}) or {})
        .get('method_parameters', {}) or {})


def parameters_of_configuration(entity):
    """
    The parameters of one notification configuration that already
    exists in a site.

    A rule cannot name a configuration — the API has no field for its
    id. It binds to the one whose parameters it repeats, so starting
    from those is what puts a rule on an existing configuration instead
    of on a copy Checkmk generates for it.
    """
    properties = (((entity or {}).get('extensions', {}) or {})
                  .get('parameter_properties', {}) or {})
    return _with_password_template(
        properties.get('method_parameters', {}) or {})


def _custom_plugin_params(value):
    """
    The keys to send next to the name of a plug-in Checkmk does not ship.

    Checkmk takes two shapes here and rejects the other one — with a 500
    for one of the combinations. A plug-in that brings its own
    configuration, the way the built-in ones do, wants its parameters as
    named fields; a plain script in the site's notifications directory
    wants the positional list it is called with.

    A value written as a dict becomes the first, a list or a plain
    comma-separated list the second. An empty field sends neither, just
    the plug-in name: which of the two shapes an empty value should mean
    cannot be guessed, and Checkmk answers a missing parameter with a
    readable error while it answers the wrong shape with a crash. A
    script that really takes no parameter is written as ``[]``.

    Raises ValueError when the value is neither.
    """
    value = (value or '').strip()
    if not value:
        return {}
    if not value.startswith(('{', '[')):
        return {'params': _split_csv(value)}
    try:
        parsed = json.loads(value)
    except ValueError:
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError) as error:
            raise ValueError(f"are not valid: {error}") from error
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {'params': parsed}
    raise ValueError("are neither a dict nor a list")


def _split_csv(value):
    """Trim+split a comma-separated string; empty input → []."""
    if not value:
        return []
    return [item.strip() for item in str(value).split(',') if item.strip()]


def _split_kv_list(value):
    """Parse "key:value,key2:value2" → [{'key': k, 'value': v}, …]."""
    out = []
    for item in _split_csv(value):
        if ':' not in item:
            continue
        key, val = item.split(':', 1)
        out.append({'key': key.strip(), 'value': val.strip()})
    return out


def _split_tag_list(value):
    """Parse "tag_group:tag_id,..." → list of tag-condition dicts."""
    out = []
    for item in _split_csv(value):
        if ':' not in item:
            continue
        group, tag_id = item.split(':', 1)
        out.append({
            'tag_type': 'tag_group',
            'tag_group': group.strip(),
            'operator': 'is',
            'tag_id': tag_id.strip(),
        })
    return out


def _split_range(value):
    """Parse "min,max" → {'from_level': int, 'to_level': int}; None on invalid."""
    parts = _split_csv(value)
    if len(parts) != 2:
        return None
    try:
        return {'from_level': int(parts[0]), 'to_level': int(parts[1])}
    except (TypeError, ValueError):
        return None


def _render(value, context):
    """Render a Jinja template against host attributes."""
    if value is None or value == '':
        return ''
    return render_jinja(value, **context).strip()


def _canonical(value):
    """Recursively canonicalize a structure for stable hashing."""
    if isinstance(value, dict):
        return tuple(sorted((k, _canonical(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_canonical(v) for v in value)
    return value


class CheckmkNotificationRuleSync(CMK2):
    """
    Export Checkmk Notification Rules.

    Identification of syncer-owned rules happens via the rule's
    description field, which we set to ``cmdbsyncer_<account_id> - DO
    NOT EDIT`` on every rule we create. There is no hash in that field
    — the diff compares the actual rule_config bodies, so manual
    changes to one of our rules in CMK are detected and corrected on
    the next run.

    The notification method is the one exception: Checkmk stores its
    parameters in a separate, admin-owned parameter set and binds a
    rule to it on creation. Since the API offers no way to point a new
    rule at a specific parameter set, a rule created with just a plugin
    name lands on Checkmk's first parameter set for that plugin. So we
    keep the method out of the drift compare and carry Checkmk's method
    block over when we rewrite a rule — otherwise every content change
    would reset the admin's notification method settings.
    """

    actions = None  # injected by inits

    DESCRIPTION_PREFIX = "cmdbsyncer_"
    DESCRIPTION_SUFFIX = " - DO NOT EDIT"

    # {reason: {'count': int, 'hosts': [sample hostnames]}} — filled while
    # the rules are built, reported once afterwards.
    _skips = None

    def export_notification_rules(self):
        """Build, dedup, diff and push notification rules to Checkmk."""
        if not self.checkmk_version.startswith(('2.4', '2.5')):
            raise CmkException(
                f"Notification rule export requires Checkmk 2.4 or 2.5; "
                f"reported version: {self.checkmk_version!r}")

        marker_full = (
            f"{self.DESCRIPTION_PREFIX}{self.account_id}{self.DESCRIPTION_SUFFIX}")
        marker_match = f"{self.DESCRIPTION_PREFIX}{self.account_id}"

        print(f"\n{CC.HEADER}Check Rule Templates{CC.ENDC}")
        self._check_rule_templates()

        print(f"\n{CC.HEADER}Build needed Notification Rules{CC.ENDC}")
        self._skips = {}
        desired = self._collect_desired_rules(marker_full)
        print(f"{CC.OKGREEN} -- {CC.ENDC} {len(desired)} rule(s) configured")
        self._report_skips()

        print(f"\n{CC.HEADER}Read Checkmk Configuration{CC.ENDC}")
        existing = self._fetch_existing_rules(marker_match)
        print(f"{CC.OKGREEN} -- {CC.ENDC} {len(existing)} syncer-owned rule(s) in CMK")

        self._diff_and_apply(desired, existing)

    def _check_rule_templates(self):
        """
        Compile every template field of every configured rule before the
        run starts. Invalid Jinja renders to an empty string, which
        normally costs the recipients and drops the whole rule — the run
        would otherwise just end with nothing built and no reason given.
        """
        defects = 0
        for rule in getattr(self.actions, 'rules', None) or []:
            for outcome in rule.outcomes:
                for field, error in validate_outcome_jinja(outcome):
                    defects += 1
                    print(f"{CC.FAIL} !! {CC.ENDC}{rule.name}: field "
                          f"'{field}' is not valid Jinja: {error}")
                    self.log_details.append(
                        ("ERROR",
                         f"{rule.name}: field '{field}' is not valid Jinja: {error}"))
        if not defects:
            print(f"{CC.OKGREEN} -- {CC.ENDC} all templates compile")
        return defects

    def _note_skip(self, reason, hostname=''):
        """
        Record why an outcome produced no rule. Each skip path is silent
        on its own — the host simply drops out — which leaves an empty
        export with nothing to look at.
        """
        if self._skips is None:
            self._skips = {}
        entry = self._skips.setdefault(reason, {'count': 0, 'hosts': []})
        entry['count'] += 1
        if hostname and len(entry['hosts']) < 3:
            entry['hosts'].append(hostname)

    def _report_skips(self):
        """Print and log what `_note_skip` collected during the build."""
        for reason, entry in sorted(self._skips.items()):
            hosts = ', '.join(entry['hosts'])
            sample = f" (e.g. {hosts})" if hosts else ""
            print(f"{CC.WARNING} !! {CC.ENDC}{entry['count']} outcome(s) "
                  f"skipped: {reason}{sample}")
            self.log_details.append(
                ("WARNING",
                 f"{entry['count']} outcome(s) skipped: {reason}{sample}"))

    def _collect_desired_rules(self, marker_full):
        rules = []
        seen = set()
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            db_objects = Host.active_non_template()
            task1 = progress.add_task("Calculate rules", total=db_objects.count())
            for db_host in db_objects:
                attributes = self.get_attributes(db_host, 'checkmk')
                if not attributes:
                    progress.advance(task1)
                    continue
                host_actions = self.actions.get_outcomes(  # pylint: disable=no-member
                    db_host, attributes['all'])
                for outcome in (host_actions or {}).get('rules', []):
                    for body in self._render_outcome(outcome, attributes['all'],
                                                     marker_full,
                                                     db_host.hostname):
                        key = _canonical(body['rule_config'])
                        if key in seen:
                            continue
                        seen.add(key)
                        rules.append(body)
                progress.advance(task1)
        return rules

    def _loop_contexts(self, outcome, attributes, hostname=''):
        """
        One render context per rule this outcome produces for a host.

        Without the loop that is a single pass with the host's own
        attributes. With it, the list expression is rendered once and
        every entry becomes a pass of its own, offered to all other
        fields as ``{{name}}`` — so one attribute holding several
        contact groups turns into one rule per group instead of one
        rule naming them all.
        """
        if not outcome.get('multiply_by_list'):
            return [{}]
        try:
            rendered = _render(outcome.get('multiply_list', ''), attributes)
        except Exception as exp:  # pylint: disable=broad-except
            logger.warning("Notification loop render error: %s", exp)
            self._note_skip(f"loop list render error: {exp}", hostname)
            return []
        if not rendered:
            self._note_skip("loop list rendered empty", hostname)
            return []
        entries = [{'name': entry} for entry in get_list(rendered) if entry]
        if not entries:
            self._note_skip("loop list rendered empty", hostname)
        return entries

    def _render_outcome(self, outcome, attributes, marker_full, hostname=''):
        """
        Turn one matched outcome into rendered API rule bodies — one
        per loop entry, or a single one when the outcome does not loop.
        """
        bodies = []
        for loop_context in self._loop_contexts(outcome, attributes, hostname):
            body = self._render_rule(
                outcome, {**attributes, **loop_context}, marker_full, hostname)
            if body is not None:
                bodies.append(body)
        return bodies

    # pylint: disable=too-many-locals
    def _render_rule(self, outcome, attributes, marker_full, hostname=''):
        """
        Turn one matched outcome into a fully rendered API rule body.
        Returns None when:
          - no recipients render (would be a silent no-op rule), or
          - the admin set match_contact_groups but it renders empty
            (would otherwise produce a nonsense match like ``''`` and
            recipients like ``_ALARM`` for hosts missing the label).
        """
        try:
            recipients = [
                r for r in _split_csv(_render(
                    outcome.get('contact_group_recipients', ''), attributes))
                if r and not r.startswith('_')
            ]
            rendered = {
                key: _render(outcome.get(key, ''), attributes)
                for key in MATCH_FIELDS
            }
        except Exception as exp:  # pylint: disable=broad-except
            logger.warning("Notification render error: %s", exp)
            self._note_skip(f"render error: {exp}", hostname)
            return None

        if not recipients:
            self._note_skip("no contact group recipients rendered", hostname)
            return None
        # If the admin specified a contact-group match template but it
        # renders empty (host missing the label), skip — otherwise the
        # rule would match every host with no CG.
        if outcome.get('match_contact_groups') and not rendered['match_contact_groups']:
            self._note_skip("contact group filter rendered empty", hostname)
            return None

        try:
            plugin_params = _custom_plugin_params(
                _render(outcome.get('notification_parameters', ''), attributes))
        except ValueError as error:
            self._note_skip(f"custom plug-in parameters {error}", hostname)
            return None

        rule_config = self._build_rule_config(
            marker_full=marker_full,
            disabled=bool(outcome.get('disable_rule')),
            notification_method=outcome.get('notification_method') or 'mail',
            notification_parameters=plugin_params,
            recipients=recipients,
            rendered=rendered,
            host_event_types=list(outcome.get('match_host_event_types') or []),
            service_event_types=list(outcome.get('match_service_event_types') or []),
        )
        return {'rule_config': rule_config}

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _build_rule_config(self, marker_full, disabled,
                           notification_method, notification_parameters,
                           recipients, rendered,
                           host_event_types,
                           service_event_types):
        """
        Assemble the CMK 2.4/2.5 rule_config dict.

        The schema is dense — every contact-selection / condition slot
        must appear with at least ``{state: disabled}``. We start from
        the full default skeleton and selectively enable only the
        slots the admin actually filled in. Drift (admin tweaked a
        slot in CMK) shows up as ``deep_compare`` mismatch on the next
        diff and triggers DELETE+POST.
        """
        contact_selection = {
            key: {'state': 'disabled'} for key in CONTACT_SELECTION_KEYS
        }
        contact_selection['members_of_contact_groups'] = {
            'state': 'enabled', 'value': recipients,
        }

        conditions = {key: {'state': 'disabled'} for key in CONDITION_KEYS}

        # CSV-list conditions
        for key in [
            'match_contact_groups', 'match_host_groups', 'match_service_groups',
            'match_sites', 'match_hosts', 'match_exclude_hosts',
            'match_services', 'match_exclude_services',
            'match_check_types', 'match_contacts',
        ]:
            values = _split_csv(rendered[key])
            if values:
                conditions[key] = {'state': 'enabled', 'value': values}

        # Key:value list conditions
        for key, splitter in [
            ('match_host_labels', _split_kv_list),
            ('match_service_labels', _split_kv_list),
            ('match_host_tags', _split_tag_list),
        ]:
            values = splitter(rendered[key])
            if values:
                conditions[key] = {'state': 'enabled', 'value': values}

        # Single-string conditions
        for key in ['match_folder', 'match_plugin_output',
                    'match_only_during_time_period']:
            value = rendered[key]
            if value:
                conditions[key] = {'state': 'enabled', 'value': value}

        levels = _split_range(rendered['match_service_levels'])
        if levels:
            conditions['match_service_levels'] = {
                'state': 'enabled', 'value': levels}

        if host_event_types:
            conditions['match_host_event_type'] = {
                'state': 'enabled',
                'value': self._event_dict(host_event_types, HOST_EVENT_FLAGS),
            }
        if service_event_types:
            conditions['match_service_event_type'] = {
                'state': 'enabled',
                'value': self._event_dict(service_event_types, SERVICE_EVENT_FLAGS),
            }

        return {
            'rule_properties': {
                'description': marker_full,
                'comment': '',
                'documentation_url': '',
                'do_not_apply_this_rule': {
                    'state': 'enabled' if disabled else 'disabled',
                },
                'allow_users_to_deactivate': {'state': 'disabled'},
            },
            'notification_method': {
                'notify_plugin': self._notify_plugin(
                    notification_method, notification_parameters),
                'notification_bulking': {'state': 'disabled'},
            },
            'contact_selection': contact_selection,
            'conditions': conditions,
        }

    @staticmethod
    def _notify_plugin(notification_method, notification_parameters):
        """
        The notification method block for one rule.

        A built-in plug-in goes out under the "following parameters"
        option and Checkmk keeps owning its parameter set. Everything
        else is rejected under that option ("Unsupported value") and has
        to be sent as a custom plug-in, with the parameters shaped by
        `_custom_plugin_params`.
        """
        if notification_method in BUILTIN_NOTIFICATION_PLUGINS:
            return {
                'option': BUILTIN_PLUGIN_OPTION,
                'plugin_params': {'plugin_name': notification_method},
            }
        return {
            'option': CUSTOM_PLUGIN_OPTION,
            'plugin_params': {
                'plugin_name': notification_method,
                **(notification_parameters or {}),
            },
        }

    @staticmethod
    def _event_dict(selected_flags, all_flags):
        """
        Build the dense {flag: bool} dict CMK expects: every known flag
        present, ``True`` for selected ones, ``False`` otherwise.
        Unknown selected flags are dropped silently.
        """
        selected = set(selected_flags) & set(all_flags)
        return {flag: (flag in selected) for flag in all_flags}

    def _fetch_existing_rules(self, marker_match):
        url = "/domain-types/notification_rule/collections/all"
        data, _headers = self.request(url, method="GET")
        rules = []
        for entry in (data or {}).get('value', []) or []:
            rule_id = (entry.get('id')
                       or entry.get('href', '').rstrip('/').split('/')[-1])
            rule_config = (entry.get('extensions', {}) or {}).get('rule_config', {}) or {}
            description = (rule_config.get('rule_properties', {}) or {}).get(
                'description', '') or ''
            if not description.startswith(marker_match):
                continue
            rules.append({'id': rule_id, 'rule_config': rule_config})
        return rules

    @staticmethod
    def _notify_plugin_block(rule_config):
        """The notify_plugin block of a rule body, never None."""
        return (rule_config.get('notification_method', {}) or {}).get(
            'notify_plugin', {}) or {}

    @classmethod
    def plugin_name(cls, rule_config):
        """Notification plugin a rule body uses."""
        notify_plugin = cls._notify_plugin_block(rule_config)
        return (notify_plugin.get('plugin_params', {}) or {}).get('plugin_name')

    @staticmethod
    def _recipients(rule_config):
        """
        Contact groups a rule notifies. Two of our rules that ship to
        the same groups are the same rule to the admin, so this is what
        we correlate on when a rule's content changed.
        """
        slot = (rule_config.get('contact_selection', {}) or {}).get(
            'members_of_contact_groups', {}) or {}
        return tuple(sorted(slot.get('value') or []))

    def _comparable(self, rule_config):
        """
        Rule body reduced to what the syncer owns.

        Everything inside ``notification_method`` except the plugin
        name — the method's parameters and the bulking settings — is
        the Checkmk admin's, so it must not count as drift. The
        parameters of a custom plug-in are the exception: those are the
        ones the syncer itself sends, so a change to them is drift.
        """
        notify_plugin = self._notify_plugin_block(rule_config)
        method = {'plugin_name': self.plugin_name(rule_config)}
        if notify_plugin.get('option') == CUSTOM_PLUGIN_OPTION:
            params = dict(notify_plugin.get('plugin_params') or {})
            params.pop('plugin_name', None)
            method['plugin_params'] = params
        reduced = dict(rule_config)
        reduced['notification_method'] = method
        return reduced

    def _diff_and_apply(self, desired, existing):
        unmatched_existing = list(existing)
        to_update = []
        to_create = []
        for body in desired:
            our_cfg = self._comparable(body['rule_config'])
            match = None
            for cmk in unmatched_existing:
                if deep_compare(our_cfg, self._comparable(cmk['rule_config'])):
                    match = cmk
                    break
            if match is not None:
                unmatched_existing.remove(match)
                continue
            # Nothing identical left. Rewrite the rule that ships to the
            # same recipients instead of deleting it and creating a new
            # one — a fresh rule would lose the notification method
            # settings the admin attached to it in Checkmk.
            for cmk in unmatched_existing:
                if self._recipients(cmk['rule_config']) == \
                        self._recipients(body['rule_config']):
                    match = cmk
                    break
            if match is not None:
                unmatched_existing.remove(match)
                to_update.append((match, body))
            else:
                to_create.append(body)
        to_delete = unmatched_existing

        print(f"\n{CC.HEADER}Apply Diff{CC.ENDC}")
        print(f"{CC.OKBLUE} *{CC.ENDC} "
              f"keep={len(desired) - len(to_create) - len(to_update)} "
              f"update={len(to_update)} create={len(to_create)} "
              f"delete={len(to_delete)}")

        if self.dry_run:
            self._report_dry_run(to_delete, to_update, to_create)
            return

        for cmk in to_delete:
            self._delete_rule(cmk['id'])
        for cmk, body in to_update:
            self._update_rule(cmk, body)
        for body in to_create:
            self._create_rule(body)

    def _describe(self, rule_config):
        """
        Short human identity of a rule body: notification plugin and
        the contact groups it ships to. The rule id says nothing to an
        admin reading a dry run.
        """
        recipients = ', '.join(self._recipients(rule_config)) or 'no recipients'
        return f"{self.plugin_name(rule_config)} -> {recipients}"

    def _report_dry_run(self, to_delete, to_update, to_create):
        """Print the pending changes instead of sending them."""
        print(f"{CC.WARNING} !{CC.ENDC} Dry run: nothing is sent to Checkmk")
        for cmk in to_delete:
            print(f"{CC.OKBLUE} *{CC.ENDC} would DELETE {cmk['id']} "
                  f"({self._describe(cmk['rule_config'])})")
        for cmk, body in to_update:
            print(f"{CC.OKBLUE} *{CC.ENDC} would UPDATE {cmk['id']} "
                  f"({self._describe(body['rule_config'])})")
        for body in to_create:
            print(f"{CC.OKBLUE} *{CC.ENDC} would CREATE "
                  f"{self._describe(body['rule_config'])}")

    def _delete_rule(self, rule_id):
        # CMK 2.4 has no real DELETE for notification rules — use the
        # action/delete/invoke POST instead. A plain DELETE returns 405.
        url = f"/objects/notification_rule/{rule_id}/actions/delete/invoke"
        try:
            self.request(url, method="POST")
            self.log_details.append(
                ("INFO", f"Deleted notification rule {rule_id}"))
            print(f"{CC.OKBLUE} *{CC.ENDC} DELETE {rule_id}")
        except CmkException as error:
            self.log_details.append(
                ("ERROR",
                 f"Could not delete notification rule {rule_id}: {error}"))
            print(f"{CC.FAIL} DELETE failed for {rule_id}: {error} {CC.ENDC}")

    def _update_rule(self, current, body):
        """
        Rewrite one of our rules in place.

        The notification method block is taken from Checkmk, not from
        us: its parameters belong to the admin, and pushing our own
        (which only names the plugin) would rebind the rule to Checkmk's
        first parameter set for that plugin. Only a changed plugin makes
        the stored parameters useless, so only then do we push ours.

        A custom plug-in is the other way round — the syncer sends its
        parameters, so ours have to win.
        """
        rule_id = current['id']
        config = dict(body['rule_config'])
        stored = current['rule_config']
        if self._notify_plugin_block(config).get('option') != CUSTOM_PLUGIN_OPTION and \
                self.plugin_name(stored) == self.plugin_name(config) and \
                stored.get('notification_method'):
            config['notification_method'] = stored['notification_method']
        url = f"/objects/notification_rule/{rule_id}"
        try:
            self.request(url, data={'rule_config': config}, method="PUT")
            self.log_details.append(
                ("INFO", f"Updated notification rule {rule_id}"))
            print(f"{CC.OKBLUE} *{CC.ENDC} UPDATE {rule_id}")
        except CmkException as error:
            self.log_details.append(
                ("ERROR",
                 f"Could not update notification rule {rule_id}: {error}"))
            print(f"{CC.FAIL} UPDATE failed for {rule_id}: {error} {CC.ENDC}")

    def _create_rule(self, body):
        url = "/domain-types/notification_rule/collections/all"
        try:
            self.request(url, data=body, method="POST")
            self.log_details.append(
                ("INFO", "Created notification rule"))
            print(f"{CC.OKBLUE} *{CC.ENDC} CREATE notification rule")
        except CmkException as error:
            self.log_details.append(
                ("ERROR",
                 f"Could not create notification rule: {error}; body={body}"))
            print(f"{CC.FAIL} CREATE failed: {error} {CC.ENDC}")
