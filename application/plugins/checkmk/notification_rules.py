"""
Checkmk Notification Rules Export

Targets the Checkmk 2.4 / 2.5 REST API. The rule body schema is
**dense**: every condition / contact-selection slot must be present,
disabled ones as ``{"state": "disabled"}``. The event-type values use
the API's lowercase flag names with every flag spelled out (``False``
by default, ``True`` for selected ones).
"""
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.models.host import Host
from application.modules.rule.rule import Rule
from application.plugins.checkmk.cmk2 import CMK2, CmkException
from application.plugins.checkmk.cmk_rules import deep_compare
from application.helpers.syncer_jinja import render_jinja
from application.modules.debug import ColorCodes as CC


NOTIFICATION_METHOD_SUGGESTIONS = [
    'mail', 'asciimail',
    'cisco_webex_teams', 'jira_issues', 'mkeventd', 'msteams',
    'opsgenie_issues', 'pagerduty', 'pushover', 'servicenow',
    'signl4', 'slack', 'sms_api_http', 'spectrum', 'victorops',
]

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
    """

    actions = None  # injected by inits

    DESCRIPTION_PREFIX = "cmdbsyncer_"
    DESCRIPTION_SUFFIX = " - DO NOT EDIT"

    def export_notification_rules(self):
        """Build, dedup, diff and push notification rules to Checkmk."""
        if not self.checkmk_version.startswith(('2.4', '2.5')):
            raise CmkException(
                f"Notification rule export requires Checkmk 2.4 or 2.5; "
                f"reported version: {self.checkmk_version!r}")

        marker_full = (
            f"{self.DESCRIPTION_PREFIX}{self.account_id}{self.DESCRIPTION_SUFFIX}")
        marker_match = f"{self.DESCRIPTION_PREFIX}{self.account_id}"

        print(f"\n{CC.HEADER}Build needed Notification Rules{CC.ENDC}")
        desired = self._collect_desired_rules(marker_full)
        print(f"{CC.OKGREEN} -- {CC.ENDC} {len(desired)} rule(s) configured")

        print(f"\n{CC.HEADER}Read Checkmk Configuration{CC.ENDC}")
        existing = self._fetch_existing_rules(marker_match)
        print(f"{CC.OKGREEN} -- {CC.ENDC} {len(existing)} syncer-owned rule(s) in CMK")

        self._diff_and_apply(desired, existing)

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
                    body = self._render_outcome(outcome, attributes['all'], marker_full)
                    if body is None:
                        continue
                    key = _canonical(body['rule_config'])
                    if key in seen:
                        continue
                    seen.add(key)
                    rules.append(body)
                progress.advance(task1)
        return rules

    # pylint: disable=too-many-locals
    def _render_outcome(self, outcome, attributes, marker_full):
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
                for key in [
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
                ]
            }
        except Exception as exp:  # pylint: disable=broad-except
            logger.warning("Notification render error: %s", exp)
            return None

        if not recipients:
            return None
        # If the admin specified a contact-group match template but it
        # renders empty (host missing the label), skip — otherwise the
        # rule would match every host with no CG.
        if outcome.get('match_contact_groups') and not rendered['match_contact_groups']:
            return None

        rule_config = self._build_rule_config(
            marker_full=marker_full,
            disabled=bool(outcome.get('disable_rule')),
            notification_method=outcome.get('notification_method') or 'mail',
            recipients=recipients,
            rendered=rendered,
            host_event_types=list(outcome.get('match_host_event_types') or []),
            service_event_types=list(outcome.get('match_service_event_types') or []),
        )
        return {'rule_config': rule_config}

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _build_rule_config(self, marker_full, disabled,
                           notification_method, recipients,
                           rendered,
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
                'notify_plugin': {
                    'option': 'create_notification_with_the_following_parameters',
                    'plugin_params': {'plugin_name': notification_method},
                },
                'notification_bulking': {'state': 'disabled'},
            },
            'contact_selection': contact_selection,
            'conditions': conditions,
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

    def _diff_and_apply(self, desired, existing):
        unmatched_existing = list(existing)
        to_create = []
        for body in desired:
            our_cfg = body['rule_config']
            match = None
            for cmk in unmatched_existing:
                if deep_compare(our_cfg, cmk['rule_config']):
                    match = cmk
                    break
            if match is not None:
                unmatched_existing.remove(match)
            else:
                to_create.append(body)
        to_delete = unmatched_existing

        print(f"\n{CC.HEADER}Apply Diff{CC.ENDC}")
        print(f"{CC.OKBLUE} *{CC.ENDC} keep={len(desired) - len(to_create)} "
              f"create={len(to_create)} delete={len(to_delete)}")

        for cmk in to_delete:
            self._delete_rule(cmk['id'])
        for body in to_create:
            self._create_rule(body)

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
