
"""
Export Checkmk Rules
"""
# pylint: disable=too-many-lines
import ast
import re
from pprint import pformat


from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, MofNCompleteColumn

from application import logger
from application.models.host import Host
from application.plugins.checkmk.cmk2 import CmkException, CMK2
from application.helpers.syncer_jinja import render_jinja, get_list
from application.modules.debug import ColorCodes as CC


def normalize_folder(folder):
    """
    Collapse repeated slashes and trim trailing ones so the rendered
    folder path matches Checkmk's rule-folder pattern. Configs that
    combine a leading "/" with a folder field that also starts with
    "/" produce "//", which the CMK API rejects outright.
    """
    folder = re.sub(r'/+', '/', folder) or '/'
    if len(folder) > 1 and folder.endswith('/'):
        folder = folder[:-1]
    return folder


def render_jinja_in_value(value, context):
    """
    Walk a debug-output value (dict / list / string) and Jinja-render
    every string that contains a ``{{ }}`` placeholder, against the
    given host attribute context. Used so the host-debug GUI shows the
    actually-rendered outcome values instead of the raw templates an
    admin configured.
    """
    if isinstance(value, dict):
        return {k: render_jinja_in_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_jinja_in_value(v, context) for v in value]
    if isinstance(value, str) and '{{' in value:
        try:
            return render_jinja(value, **context)
        except Exception:  # pylint: disable=broad-except
            return value
    return value


def preview_rule_for_attributes(rule, attributes):
    """
    Render every outcome of a ``CheckmkRuleMngmt`` against the given
    host attributes for the host-debug GUI. No Checkmk API call, no
    version probe — only Jinja-rendering of the fields the export
    pipeline would also render. ``loop_over_list`` outcomes expand
    into one entry per loop value.
    """
    results = []
    for outcome in rule.outcomes:
        if outcome.loop_over_list and outcome.list_to_loop:
            loop_list = get_list(attributes.get(outcome.list_to_loop, ''))
            if not loop_list:
                results.append(_render_outcome_preview(
                    outcome, attributes,
                    note=(f"loop_over_list active, but '{outcome.list_to_loop}' "
                          f"is empty for this host — no rule would be exported"),
                ))
                continue
            for loop_idx, loop_value in enumerate(loop_list):
                results.append(_render_outcome_preview(
                    outcome, attributes, loop_value=loop_value, loop_idx=loop_idx,
                ))
        else:
            results.append(_render_outcome_preview(outcome, attributes))
    return results


def _safe_render_factory(context):
    """Closure over the host-attribute Jinja context used by the previews."""
    def _safe_render(template):
        if not template:
            return ''
        try:
            return render_jinja(template, **context)
        except Exception as exp:  # pylint: disable=broad-except
            return f"!! render error: {type(exp).__name__}: {exp}"
    return _safe_render


def _render_outcome_preview(outcome, attributes, loop_value=None,
                            loop_idx=None, note=None):
    """
    Jinja-render a single ``RuleMngmtOutcome`` against the host's
    attributes and return the generic ``{title, meta, rows, note}``
    preview shape consumed by the debug template.
    """
    context = dict(attributes)
    if loop_value is not None:
        context['loop'] = loop_value
        context['loop_idx'] = loop_idx
    render = _safe_render_factory(context)

    rows = [
        ('folder', normalize_folder(render(outcome.folder or '/'))),
        ('value', render(outcome.value_template)),
    ]
    if outcome.condition_host:
        rows.append(('condition_host', render(outcome.condition_host)))
    if outcome.condition_label_template:
        rows.append(('condition_label', render(outcome.condition_label_template)))
    if outcome.condition_service:
        rows.append(('condition_service', render(outcome.condition_service)))
    if outcome.condition_service_label:
        rows.append(('condition_service_label',
                     render(outcome.condition_service_label)))

    meta_parts = [f"folder_index={outcome.folder_index}"]
    if loop_idx is not None:
        meta_parts.append(f"loop[{loop_idx}] = {loop_value}")
    if outcome.comment:
        meta_parts.append(render(outcome.comment))

    return {
        'title': outcome.ruleset or '— no ruleset —',
        'meta': ' · '.join(meta_parts),
        'rows': rows,
        'note': note,
    }


def preview_group_rule_for_attributes(rule, attributes):
    """
    Render a ``CheckmkGroupRule`` outcome against a single host's
    attributes for the host-debug GUI.

    The production export aggregates label keys / values across every
    host before deciding which groups to create. For the per-host
    debug page we restrict that aggregation to the selected host's
    own attributes — the result tells the admin "for *this* host this
    rule contributes the following group(s)". ``foreach_type='object'``
    is intrinsically cross-host (it iterates objects from an account)
    and is reported as such instead of pretending to evaluate.
    """
    outcome = rule.outcome
    if not outcome:
        return [{
            'title': '— empty rule —',
            'meta': '',
            'rows': [],
            'note': 'This group rule has no outcome configured.',
        }]

    foreach = outcome.foreach or ''
    foreach_type = outcome.foreach_type or ''
    group_type = outcome.group_name or ''

    if foreach_type == 'object':
        return [{
            'title': f"{group_type} ({foreach_type})",
            'meta': f"foreach={foreach!r}",
            'rows': [],
            'note': ("foreach_type='object' iterates Account-objects across "
                     "all hosts — this preview only inspects a single host, "
                     "so the per-host outcome is not meaningful here. The "
                     "export will create one group per matching object."),
        }]

    items = _collect_group_items_for_host(foreach_type, foreach, attributes)

    if not items:
        return [{
            'title': f"{group_type} ({foreach_type})",
            'meta': f"foreach={foreach!r}",
            'rows': [],
            'note': (f"No matching items on this host for "
                     f"foreach_type={foreach_type!r}, foreach={foreach!r} "
                     f"— this rule would not contribute a group for this host."),
        }]

    render = _safe_render_factory(dict(attributes))
    results = []
    for item in items:
        rows = [('source_item', str(item))]
        if outcome.rewrite:
            try:
                rendered_name = render_jinja(
                    outcome.rewrite, name=item, result=item, **attributes)
            except Exception as exp:  # pylint: disable=broad-except
                rendered_name = f"!! render error: {type(exp).__name__}: {exp}"
        else:
            rendered_name = str(item)
        if outcome.rewrite_title:
            try:
                rendered_title = render_jinja(
                    outcome.rewrite_title, name=item, result=item, **attributes)
            except Exception as exp:  # pylint: disable=broad-except
                rendered_title = f"!! render error: {type(exp).__name__}: {exp}"
        else:
            rendered_title = str(item)
        rows.append(('group_name', rendered_name))
        rows.append(('group_title', rendered_title))
        # Reuse `render` so attribute-driven rewrites stay consistent
        # even if a future field gains Jinja support without `name=`.
        _ = render  # keep the helper present for symmetry / future use

        results.append({
            'title': f"{group_type}: {rendered_name}",
            'meta': f"foreach_type={foreach_type}",
            'rows': rows,
            'note': None,
        })
    return results


def _collect_group_items_for_host(foreach_type, foreach, attributes):
    """
    Mirror ``CheckmkGroupSync`` collection logic but restricted to
    one host's attributes so the GUI debug page can show what groups
    the rule would contribute for *this* host. Production exports
    aggregate across every host; for a per-host preview we only look
    at this host's labels / inventory.
    """
    if not foreach:
        return []

    collectors = {
        'value': _collect_group_items_value,
        'label': _collect_group_items_label,
        'list': _collect_group_items_list,
    }
    collect = collectors.get(foreach_type)
    return collect(foreach, attributes) if collect else []


def _collect_group_items_value(foreach, attributes):
    """For ``foreach_type='value'`` — keys on this host whose own value
    is exactly ``foreach`` (or any key starting with ``prefix*``
    contributes its values)."""
    items = []
    if foreach.endswith('*'):
        prefix = foreach[:-1]
        for key, value in attributes.items():
            if key.startswith(prefix):
                items.extend(get_list(value))
    else:
        for key, value in attributes.items():
            if str(value) == foreach:
                items.append(key)
    return items


def _collect_group_items_label(foreach, attributes):
    """For ``foreach_type='label'`` — this host's value(s) for label
    ``foreach`` (prefix*: collect values of every matching label)."""
    if foreach.endswith('*'):
        prefix = foreach[:-1]
        items = []
        for key, value in attributes.items():
            if key.startswith(prefix):
                items.extend(get_list(value))
        return items
    value = attributes.get(foreach)
    if value is None or value == '':
        return []
    return get_list(value)


def _collect_group_items_list(foreach, attributes):
    """For ``foreach_type='list'`` — flatten the host attribute that
    holds the list."""
    items = []
    for entry in get_list(attributes.get(foreach, [])):
        items.extend(get_list(entry))
    return items


def get_preview_providers():
    """
    Registry of host-debug rule previews. Each provider lists the
    rule-type slug used in URLs, a human label, the MongoEngine
    model that backs the dropdown, and the renderer that turns one
    rule + the host attributes into the outcome-dict shape the
    debug template expects (see ``_render_outcome_preview``).

    Adding a new rule type to the GUI debugger is a one-liner here:
    register ``(model, render_fn)`` and the dropdown / dispatch /
    template all pick it up automatically.
    """
    # pylint: disable=import-outside-toplevel
    from .models import CheckmkRuleMngmt, CheckmkGroupRule
    return {
        'setup_rule': {
            'label': 'Setup Rule',
            'model': CheckmkRuleMngmt,
            'render': preview_rule_for_attributes,
        },
        'group_rule': {
            'label': 'Manage Group',
            'model': CheckmkGroupRule,
            'render': preview_group_rule_for_attributes,
        },
    }


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

def deep_compare(ours, stored):
    """
    Check whether our configured rule value is equivalent to the value
    Checkmk has stored. Asymmetric on dict keys: Checkmk normalises rule
    values on save, often enriching them with schema defaults we did not
    explicitly set. Treating every extra stored key as drift produces an
    endless UPDATE/DELETE churn — so we only require that every key we
    set matches; stored extras are accepted as defaults.

    List items are compared order-insensitive to tolerate reorderings.
    Nested dicts inside lists are still compared structurally via each
    element's ``==``.
    """
    if isinstance(ours, dict) and isinstance(stored, dict):
        ours = clean_postproccessed(ours)
        stored = clean_postproccessed(stored)
        if not set(ours.keys()).issubset(set(stored.keys())):
            return False
        return all(deep_compare(v, stored[k]) for k, v in ours.items())
    if isinstance(ours, list) and isinstance(stored, list):
        return sorted(ours, key=str) == sorted(stored, key=str)
    return ours == stored


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
        # Captured in clean_rules: ordered list of syncer-owned CMK rule
        # IDs as they appeared in the GET response, per ruleset. Used by
        # sort_rules to skip the move chain when CMK already lists the
        # rules in the desired order.
        self._cmk_order_by_ruleset = {}

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
        rule_params['folder'] = normalize_folder(
            render_jinja(rule_params['folder'], **context))
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
        self._sort_rulsets_by_intent()
        self.clean_rules()
        self.create_rules()
        self.sort_rules()


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



    def _sort_rulsets_by_intent(self):
        """
        Stable-sort every ``rulsets_by_type[ruleset]`` list by the
        ``folder_index`` carried on each ``RuleMngmtOutcome``. The
        rule-engine already iterates ``CheckmkRuleMngmt`` in
        ``sort_field`` order (see ``inits.export_rules``), and stable
        sort preserves that ordering for outcomes sharing the same
        ``folder_index`` (default 0). Sorting before ``create_rules``
        means the POST loop already creates rules in the desired
        order; ``sort_rules`` then enforces the order in Checkmk.
        """
        for ruleset_name, rules in self.rulsets_by_type.items():
            rules.sort(
                key=lambda r: (r.get('folder', '/'), r.get('folder_index', 0)),
            )
            self.rulsets_by_type[ruleset_name] = rules

    def sort_rules(self):
        """
        Reorder syncer-owned rules in each Checkmk ruleset so they
        appear in the ``folder_index`` / ``sort_field`` order the
        admin configured. Only rules with our description marker
        (``cmdbsyncer_{account_id}``) are moved — user-created rules
        in the same ruleset are never touched.

        The chosen strategy chains ``after_specific_rule`` moves
        anchored to the first syncer rule's current position: the
        first rule keeps its place relative to user rules around it,
        every subsequent syncer rule is pulled to sit right after the
        previous one. This minimises disruption to user rules
        compared to a ``top_of_folder`` / ``bottom_of_folder`` sweep
        that would push the syncer block past every user rule.
        """
        print(f"{CC.OKGREEN} -- {CC.ENDC} Reorder syncer rules")
        with Progress(SpinnerColumn(),
                      MofNCompleteColumn(),
                      *Progress.get_default_columns(),
                      TimeElapsedColumn()) as progress:
            task1 = progress.add_task(
                "Sort Rules", total=len(self.rulsets_by_type),
            )
            for ruleset_name, rules in self.rulsets_by_type.items():
                if len(rules) < 2:
                    progress.advance(task1)
                    continue
                # folder_index defaults to 0; if no rule in this ruleset
                # has an explicit folder_index > 0, the admin has not
                # configured an order — leave the Checkmk-side ordering
                # untouched instead of chaining a move per rule.
                if not any(r.get('folder_index', 0) for r in rules):
                    progress.advance(task1)
                    continue
                desired_ids = self._desired_cmk_id_chain(rules)
                if len(desired_ids) < 2:
                    progress.advance(task1)
                    continue
                # Skip the move chain when CMK already lists the
                # syncer-owned rules in the desired order.
                if self._is_already_sorted(ruleset_name, rules, desired_ids):
                    progress.advance(task1)
                    continue
                for i in range(1, len(desired_ids)):
                    move_url = (
                        f"objects/rule/{desired_ids[i]}/actions/move/invoke"
                    )
                    payload = {
                        "position": "after_specific_rule",
                        "rule_id": desired_ids[i - 1],
                    }
                    try:
                        self.request(move_url, data=payload, method="POST")
                        self.log_details.append((
                            "INFO",
                            f"Reordered rule in {ruleset_name}: "
                            f"{desired_ids[i]} after {desired_ids[i - 1]}",
                        ))
                    except CmkException as error:
                        message = (
                            f"Could not reorder rule {desired_ids[i]} in "
                            f"{ruleset_name}: {error}"
                        )
                        self.log_details.append(("ERROR", message))
                        print(f"{CC.FAIL} {message} {CC.ENDC}")
                    except Exception as error:  # pylint: disable=broad-except
                        # A non-CmkException (timeout, network reset, JSON
                        # decode, …) used to bubble out of sort_rules and
                        # silently abort the rest of the reorder. Catch it
                        # explicitly so the run continues and the failure
                        # is visible on stdout and in the run log.
                        message = (
                            f"Unexpected error reordering rule {desired_ids[i]} in "
                            f"{ruleset_name}: {type(error).__name__}: {error}"
                        )
                        self.log_details.append(("ERROR", message))
                        print(f"{CC.FAIL} {message} {CC.ENDC}")
                progress.advance(task1)

    def _desired_cmk_id_chain(self, rules):
        """
        Build the ordered list of Checkmk rule IDs for ``sort_rules``.

        IDs are captured on the local rule dict at create-time
        (``create_rules``) and at keep-time (``clean_rules``); we just
        read them back here. Content-based matching against a fresh
        GET of the ruleset is unreliable when several outcomes share
        the same conditions+value (different comments only) — the
        matcher would then bind in CMK-return order and silently
        cancel the desired sort.
        """
        return [
            rule['_cmk_id'] for rule in rules
            if rule.get('_cmk_id')
        ]

    def _is_already_sorted(self, ruleset_name, rules, desired_ids):
        """
        Return True when CMK already lists the syncer-owned rules in
        ``desired_ids`` order, so ``sort_rules`` can skip the move
        chain entirely. The snapshot was taken in ``clean_rules`` from
        the GET response — valid only when no rule in the chain was
        freshly created since (a fresh POST lands at the bottom of the
        folder, outside the captured order). ``_skip_create`` marks
        rules that ``clean_rules`` paired with an existing CMK rule;
        anything missing that flag was created during this run and
        forces the chain.
        """
        for rule in rules:
            if rule.get('_cmk_id') and not rule.get('_skip_create'):
                return False
        captured = self._cmk_order_by_ruleset.get(ruleset_name)
        if not captured:
            return False
        desired_set = set(desired_ids)
        cmk_subset = [rid for rid in captured if rid in desired_set]
        return cmk_subset == desired_ids

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


                    if rule.get('_skip_create'):
                        # ``clean_rules`` already paired this entry with
                        # an existing Checkmk rule (full match or in-
                        # place update). No POST needed; the captured
                        # ``_cmk_id`` is what ``sort_rules`` will move.
                        continue
                    print(f"{CC.OKBLUE} *{CC.ENDC} Create Rule in {ruleset_name} " \
                          f"({rule['condition']})")
                    url = "domain-types/rule/collections/all"
                    try:
                        response = self.request(url, data=template, method="POST")
                        # Checkmk returns the freshly created rule's
                        # JSON body; pin its id on the local entry so
                        # ``sort_rules`` can chain after_specific_rule
                        # moves without round-tripping a GET + content
                        # match (which is ambiguous when multiple
                        # outcomes share conditions+value).
                        try:
                            rule['_cmk_id'] = response[0].get('id')
                        except (TypeError, IndexError, AttributeError):
                            rule['_cmk_id'] = None
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
                # Capture the order of syncer-owned rule IDs as CMK
                # currently lists them. sort_rules uses this snapshot to
                # skip the move chain when the desired order already
                # matches reality.
                self._cmk_order_by_ruleset[ruleset_name] = [
                    cmk_rule['id'] for cmk_rule in rule_response['value']
                    if cmk_rule['extensions']['properties'].get('description', '')
                    == f'cmdbsyncer_{self.account_id}'
                ]
                for cmk_rule in rule_response['value']:
                    if cmk_rule['extensions']['properties'].get('description', '') != \
                        f'cmdbsyncer_{self.account_id}':
                        continue



                    value = cmk_rule['extensions']['value_raw']
                    cmk_condition = cmk_rule['extensions']['conditions']
                    rule_found = False
                    condition_matches = []  # Collect all rules with matching conditions

                    cmk_comment = cmk_rule['extensions']['properties'].get(
                        'comment', '')
                    for rule in list(rules):
                        # ``sort_rules`` needs every owned rule to keep
                        # its (rulesets_by_type) slot with a captured
                        # ``_cmk_id``. Skip entries already paired with
                        # a different cmk_rule on a previous iteration
                        # of this outer loop — re-matching them would
                        # only produce duplicates.
                        if rule.get('_skip_create'):
                            continue
                        try:
                            cmk_value = ast.literal_eval(rule['value'])
                            check_value = ast.literal_eval(value)
                        except (SyntaxError, KeyError):
                            logger.debug("Invalid Value: '%s' or '%s'", rule['value'], value)
                            continue

                        condition_match = rule['condition'] == cmk_condition
                        # Comment is admin-supplied free text per outcome
                        # (RuleMngmtOutcome.comment). When several
                        # outcomes share the same condition+value the
                        # comment is the only distinguishing identifier
                        # — without it ``sort_rules`` ends up pairing
                        # local→cmk in CMK iteration order, silently
                        # cancelling the configured folder_index
                        # ordering on idempotent re-runs.
                        comment_match = rule.get('comment', '') == cmk_comment
                        value_match = deep_compare(cmk_value, check_value)

                        # Collect all rules with matching conditions
                        if condition_match:
                            condition_matches.append({
                                'rule': rule,
                                'expected_value': cmk_value,
                                'actual_value': check_value,
                                'value_match': value_match
                            })

                        if condition_match and comment_match and value_match:
                            logger.debug("FULL MATCH")
                            rule_found = True
                            # Pin the cmk_rule id on the local entry and
                            # mark it skip-create so create_rules leaves
                            # it alone but sort_rules can still reorder
                            # it. The entry stays in ``rules`` so the
                            # sort step sees a contiguous picture of
                            # every owned rule.
                            rule['_cmk_id'] = cmk_rule['id']
                            rule['_skip_create'] = True
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
                            our_rule['_cmk_id'] = rule_id
                            our_rule['_skip_create'] = True
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
