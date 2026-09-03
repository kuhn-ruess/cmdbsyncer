
"""
Export Checkmk Rules
"""
# pylint: disable=too-many-lines
import ast
import json
import re
from collections import Counter
from pprint import pformat


from mongoengine.errors import DoesNotExist

from application import app, logger
from application.models.host import Host
from application.plugins.checkmk.cmk2 import CmkException, CMK2
from application.helpers.syncer_jinja import render_jinja, get_list
from application.plugins.checkmk.helpers import make_progress, resolve_loop_list
from application.helpers.label_hash import syncer_hash
from application.modules.debug import ColorCodes as CC


# Appended to the rule comment when an outcome opts into keeping a manually
# adjusted value. Must stay identical between create and compare.
KEEP_VALUE_HINT = "Value managed manually in Checkmk - Syncer will not overwrite it."

# Appended to the rule description of a ``keep_value`` outcome, so the Checkmk
# rule list already says the value may be adjusted there.
KEEP_VALUE_MARK = "(Value editable)"

# Longest Setup Rule name written into the Checkmk rule description. Long
# enough for real rule names, short enough to keep the rule list readable.
DESCRIPTION_NAME_LIMIT = 60

# Fields of a ``RuleMngmtOutcome`` that identify the Setup Rule it was
# configured in. Everything else is bookkeeping (folder_index, loop flags)
# or a flag that does not tell two rules apart.
OUTCOME_IDENTITY_KEYS = (
    'ruleset', 'folder', 'value_template', 'comment',
    'condition_label_template', 'condition_host',
    'condition_service', 'condition_service_label',
)


def outcome_signature(outcome):
    """
    Stable key of an outcome in the shape it is stored in the rule document.

    The export reads its outcomes from the per-host cache, which does not
    carry the name of the Setup Rule they came from - writing it there would
    copy the name into every host document. Matching a cached outcome back
    onto the loaded rules by content recovers the name without storing it.
    """
    return tuple(str(outcome.get(key) or '') for key in OUTCOME_IDENTITY_KEYS)

# Condition keys of the rule payload, per family. Both spellings are listed:
# Checkmk 2.2 takes flat label lists, 2.3+ label groups (see
# build_condition_and_update_rule_params).
SERVICE_LABEL_KEYS = ('service_labels', 'service_label_groups')
HOST_LABEL_KEYS = ('host_labels', 'host_label_groups')
SERVICE_CONDITION_KEYS = ('service_description',) + SERVICE_LABEL_KEYS


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


def normalize_cmk_folder(folder):
    """
    Canonicalise a folder path coming back from the Checkmk REST API so it
    can be compared against a user-entered folder.

    Checkmk returns rule folders either slash-delimited ("/server/windows")
    or tilde-delimited ("~server~windows", "~" for root). Both are collapsed
    to the slash form ``normalize_folder`` already uses on the export side.
    """
    folder = (folder or '/').replace('~', '/')
    return normalize_folder(folder)


# A Checkmk host label carries a short scalar; anything longer is a data
# dump that would never be typed into a rule condition.
MAX_LABEL_VALUE_LEN = 80
# How much of a group a label has to cover to be worth reporting as a
# near miss.
PARTIAL_LABEL_COVERAGE = 0.8
# Filter rule that 'analyse_rules --apply' collects its whitelists in.
APPLY_FILTER_RULE_NAME = 'Syncer: attributes used by rule conditions'
# Characters that make an attribute unusable as a single Checkmk label:
# a comma means the value is really a list, the rest are wildcard and
# regex metacharacters, i.e. a pattern rather than a value.
# A colon separates key from value in a label condition, so neither half
# may carry one — values have theirs replaced before the check, the way
# the export does it.
INVALID_LABEL_CHARS = set(',:*?^$()[]{}|\\/"\'')
# Appended to an attribute name when only a hash of its value can be a
# label. The Rewrite rule 'analyse_rules --apply' writes uses the same
# name, so the condition and the exported label line up.
HASHED_LABEL_SUFFIX = '_hash'
# Rewrite rule that 'analyse_rules --apply' collects its hashes in.
APPLY_REWRITE_RULE_NAME = 'Syncer: hashed attributes for rule conditions'


def _hash_template_filters(transform):
    """
    The Jinja filter chain a hash rewrite uses.

    ``transform=True`` hashes the value the way it would have been
    written as a label (colon replaced, optionally lowercased) — that is
    the value the analysis hashed for the condition, so both sides have
    to agree. Without it the raw value is hashed, which is what the
    analysis does for attributes that cannot be a label at all.
    """
    chain = ""
    if transform:
        chain += " | replace(':', '-')"
        if app.config.get('CMK_LOWERCASE_LABEL_VALUES'):
            chain += " | lower"
    return chain + " | hash"


def _usable_as_label(text):
    """
    Whether ``text`` can be one half of a ``key:value`` label condition.

    Rejects what only looks like a value: comma-separated lists, service
    and regex patterns, wildcards, and anything carrying whitespace —
    matching on those is guesswork, and suggesting them produces a
    condition that matches nothing or the wrong hosts.
    """
    if not text or text != text.strip():
        return False
    if any(char.isspace() for char in text):
        return False
    return not INVALID_LABEL_CHARS.intersection(text)


def shorten_value(value, limit=120):
    """
    One-line, length-capped rendering of a rule value for reports.
    """
    value = str(value).replace('\n', ' ')
    if len(value) > limit:
        return value[:limit] + '…'
    return value


def findings_for_storage(results):
    """
    The findings as plain documents the web interface can render and
    apply without re-running an analysis that walks every host twice.

    ``exported_keys`` is deliberately not carried along — it is the same
    (potentially huge) set for every finding. All that matters per
    finding is whether its own label still has to be let through the
    filter, so that is reduced to a flag here.
    """
    def labels(entries, exported):
        return [{
            'key': label[0], 'value': label[1], 'source': label[2],
            'inside': inside, 'outside': outside,
            'needs_filter': label[0] not in exported,
        } for label, inside, outside in entries]

    stored = []
    for result in results:
        exported = result.get('exported_keys') or set()
        rule = result['rule']
        comment = (rule.get('comment') or '').splitlines()
        stored.append({
            'ruleset': result['ruleset'],
            'folder': rule.get('folder', '/'),
            'comment': comment[0] if comment else '',
            'value': shorten_value(rule.get('value', '')),
            'hosts': result['hosts'],
            'syncer_rules': [list(entry) for entry in result['syncer_rules']],
            'label_condition_kept': result['label_condition_kept'],
            'outcome_rules': result.get('outcome_rules', 1),
            'exact': labels(result['exact'], exported),
            'wider': labels(result['wider'][:3], exported),
            'partial': labels(result['partial'][:3], exported),
        })
    return stored


def finding_from_storage(finding):
    """
    Turn a stored finding back into the shape ``_apply_finding`` expects,
    so the web interface can apply one without a fresh analysis.
    """
    exported = {label['key'] for label in finding.get('exact', [])
                if not label.get('needs_filter')}
    return {
        'ruleset': finding['ruleset'],
        'rule': {'folder': finding.get('folder', '/')},
        'syncer_rules': [tuple(entry)
                         for entry in finding.get('syncer_rules', [])],
        'hosts': finding.get('hosts', 0),
        'label_condition_kept': finding.get('label_condition_kept', True),
        # 0 = the analysis that produced this finding did not count them
        # yet; the apply step refuses rather than guessing.
        'outcome_rules': finding.get('outcome_rules', 0),
        'exact': [((label['key'], label['value'], label['source']),
                   label['inside'], label['outside'])
                  for label in finding.get('exact', [])],
        'wider': [], 'partial': [],
        'exported_keys': exported,
    }


def condition_hosts(condition):
    """
    The host list of a rule condition, or an empty list when the condition
    does not target hosts by name.
    """
    host_name = (condition or {}).get('host_name')
    if isinstance(host_name, dict):
        return list(host_name.get('match_on') or [])
    return []


def condition_without_hosts(condition):
    """
    Copy of a rule condition with the host name match list removed.

    ``optimize_rules`` coalesces every host sharing an outcome into a
    single rule, so that list is exactly the part which legitimately
    changes from run to run — a host being added or dropped must adjust
    the existing rule instead of making it look like a different one.
    """
    stripped = dict(condition or {})
    host_name = stripped.get('host_name')
    if isinstance(host_name, dict) and 'match_on' in host_name:
        host_name = dict(host_name)
        host_name.pop('match_on')
        stripped['host_name'] = host_name
    return stripped


def scope_folder(folder):
    """
    Normalise a folder for a folder-scope selection.

    Like :func:`normalize_cmk_folder`, but also prefixes a leading ``/`` and
    lowercases the path when ``CMK_LOWERCASE_FOLDERNAMES`` is on. Checkmk's API
    folder names are always lowercase, and the export side (``rules.py``) writes
    them that way, so a picked or typed folder compares equal to the folder a
    host actually lands in.
    """
    folder = (folder or '').strip()
    if folder and not folder.startswith('/'):
        folder = '/' + folder
    folder = normalize_cmk_folder(folder)
    if app.config['CMK_LOWERCASE_FOLDERNAMES']:
        folder = folder.lower()
    return folder


def folder_in_scope(rule_folder, target_folder, recursive=False):
    """
    True when ``rule_folder`` should be imported for ``target_folder``.

    Without ``recursive`` only an exact folder match counts; with it every
    folder at or below ``target_folder`` matches. Both sides are normalised
    first so "/server/windows", "server/windows/" and "~server~windows" are
    treated as equal.
    """
    rule_folder = normalize_cmk_folder(rule_folder)
    target_folder = normalize_cmk_folder(target_folder)
    if rule_folder == target_folder:
        return True
    if not recursive:
        return False
    if target_folder == '/':
        return True
    return rule_folder.startswith(target_folder + '/')


def folder_within_scope(folder, limits):
    """
    True when ``folder`` falls within an account's ``limit_by_folders`` scope.

    ``limits`` is the raw comma-separated ``limit_by_folders`` value off the
    account. An empty or missing scope means no restriction (always True).
    Folders typed without a leading slash are tolerated, and the match is
    recursive so selecting ``/test`` also covers ``/test/linux``. Shared by the
    host export (which folder a host lands in) and the rule export (which folder
    a Setup rule is placed in) so both honour the same scope.
    """
    allowed = []
    for entry in (limits or '').split(','):
        entry = entry.strip()
        if not entry:
            continue
        if not entry.startswith('/'):
            entry = '/' + entry
        allowed.append(entry)
    if not allowed:
        return True
    folder = folder or '/'
    return any(folder_in_scope(folder, scope, recursive=True) for scope in allowed)


def parse_label(rendered):
    """
    Split a Checkmk label into a stripped ``(key, value)`` tuple.

    A label is ``key:value``. The value itself may legitimately contain
    colons (e.g. a URL), so only the FIRST colon separates key from value.
    Returns ``None`` when the input is not a well-formed single label — no
    colon, or an empty key or value. The old bare ``str.split(':')`` both
    crashed on a second colon and silently dropped rules on an empty half;
    callers now decide what to do with the ``None``.
    """
    if not rendered or ':' not in rendered:
        return None
    key, value = rendered.split(':', 1)
    key, value = key.strip(), value.strip()
    if not key or not value:
        return None
    return key, value


_JINJA_SPAN = re.compile(r'\{\{.*?\}\}|\{%.*?%\}', re.DOTALL)


def _has_jinja(text):
    """True if the value opens a Jinja expression/block — its rendered
    result is only known per host, so it is exempt from static shape checks."""
    return '{{' in text or '{%' in text


def _has_jinja_fragment(text):
    """True if the text carries ANY Jinja delimiter, opening or closing. Used
    to skip fragments produced when a comma inside a Jinja expression splits a
    template segment, so they are not mistaken for a malformed literal label."""
    return any(tok in text for tok in ('{{', '}}', '{%', '%}'))


def _strip_jinja(text):
    """Drop complete Jinja expressions/blocks so only the hand-typed literal
    text remains — lets us judge literal structure (e.g. a stray comma)
    without guessing what the Jinja will render to."""
    return _JINJA_SPAN.sub('', text)


def label_condition_problems(host_label='', service_label=''):
    """
    Static validation of the Host/Service label condition fields for the
    save-time form check. Reports only problems that hold regardless of what
    any Jinja renders to: a literal comma in the single-valued Host label, and
    a fully-static Service label entry that is not 'key:value'. Jinja-bearing
    values are otherwise trusted (validated per host at export time). Returns a
    list of human-readable messages, empty when nothing is statically wrong.
    """
    problems = []
    host_label = (host_label or '').strip()
    if host_label:
        if ',' in _strip_jinja(host_label):
            problems.append(
                "Host label condition takes a single 'key:value' — remove the "
                f"comma from '{host_label}'")
        elif not _has_jinja(host_label) and not parse_label(host_label):
            problems.append(
                f"Host label condition must be 'key:value', got '{host_label}'")
    service_label = (service_label or '').strip()
    if service_label:
        bad = [seg.strip() for seg in service_label.split(',')
               if seg.strip() and not _has_jinja_fragment(seg)
               and not parse_label(seg.strip())]
        if bad:
            problems.append(
                "Service label conditions must be 'key:value' — fix "
                + ', '.join(repr(b) for b in bad))
    return problems


def iter_rule_folders():
    """
    Collect the literal folders that the configured rules can place objects
    in, so a UI can offer them for selection (the ``limit_by_folders`` scope
    used to populate a Checkmk test instance).

    Sources:
      * ``CheckmkRuleMngmt`` outcome folders — where Setup rules are placed,
      * ``CheckmkRule`` outcomes with action ``move_folder`` / ``create_folder``
        — where hosts are moved/created (literal params only; Jinja-templated
        folders, i.e. those containing ``{{``, can't be resolved statically and
        are skipped — they still match at export time via the recursive scope),
      * ``CheckmkFolderPool.folder_name`` — pool folders.

    Returns a sorted list of unique, normalised folder paths.
    """
    from .models import (  # pylint: disable=import-outside-toplevel
        CheckmkRuleMngmt,
        CheckmkRule,
        CheckmkFolderPool,
    )
    folders = set()

    for rule in CheckmkRuleMngmt.objects():
        for outcome in rule.outcomes:
            if outcome.folder and '{{' not in outcome.folder:
                folders.add(scope_folder(outcome.folder))

    for rule in CheckmkRule.objects(enabled=True):
        for outcome in rule.outcomes:
            if outcome.action not in ('move_folder', 'create_folder'):
                continue
            param = (outcome.action_param or '').strip()
            if not param or '{{' in param:
                continue
            folders.add(scope_folder(param))

    for pool in CheckmkFolderPool.objects():
        if pool.folder_name:
            folders.add(scope_folder(pool.folder_name))

    return sorted(folders)


def cmk_conditions_to_outcome(conditions):
    """
    Reverse of ``build_condition_and_update_rule_params``: turn a Checkmk
    rule ``conditions`` object back into the ``RuleMngmtOutcome`` condition
    fields (condition_host / _label_template / _service / _service_label).

    Handles both the 2.2 (``host_labels``/``service_labels``) and the 2.3+
    (``host_label_groups``/``service_label_groups``) shapes and tolerates
    missing keys. Only the first host label is representable in the outcome
    model, matching the export side which also emits a single label.
    """
    conditions = conditions or {}
    result = {
        'condition_host': '',
        'condition_label_template': '',
        'condition_service': '',
        'condition_service_label': '',
    }

    host_name = conditions.get('host_name') or {}
    if host_name.get('match_on'):
        result['condition_host'] = ','.join(host_name['match_on'])

    service = conditions.get('service_description') or {}
    if service.get('match_on'):
        result['condition_service'] = ','.join(service['match_on'])

    # Host label: 2.3+ nested label_groups, else flat 2.2 host_labels.
    label = _first_label_from_groups(conditions.get('host_label_groups'))
    if not label:
        host_labels = conditions.get('host_labels') or []
        if host_labels:
            first = host_labels[0]
            if first.get('key') and first.get('value') is not None:
                label = f"{first['key']}:{first['value']}"
    result['condition_label_template'] = label or ''

    # Service labels: collect every label across the groups.
    svc_labels = _all_labels_from_groups(conditions.get('service_label_groups'))
    if not svc_labels:
        svc_labels = [
            entry for entry in (conditions.get('service_labels') or [])
            if isinstance(entry, str)
        ]
    result['condition_service_label'] = ','.join(svc_labels)

    return result


def _first_label_from_groups(label_groups):
    """Return the first ``key:value`` label found in a *_label_groups list."""
    for group in label_groups or []:
        for entry in group.get('label_group') or []:
            if entry.get('label'):
                return entry['label']
    return ''


def _all_labels_from_groups(label_groups):
    """Return every ``key:value`` label found across *_label_groups."""
    labels = []
    for group in label_groups or []:
        for entry in group.get('label_group') or []:
            if entry.get('label'):
                labels.append(entry['label'])
    return labels


def cmk_rule_to_outcome(cmk_rule):
    """
    Convert one Checkmk rule object (as returned by the REST API under
    ``value`` in a rule collection) into a ``RuleMngmtOutcome``-shaped dict.

    The rule's literal ``value_raw`` becomes the outcome's value_template and
    its conditions are reversed via ``cmk_conditions_to_outcome`` — so the
    imported rule, exported as a static rule, reproduces the exact same
    Checkmk rule.
    """
    extensions = cmk_rule.get('extensions', {}) or {}
    outcome = {
        'ruleset': extensions.get('ruleset', ''),
        'folder': normalize_cmk_folder(extensions.get('folder', '/')),
        'folder_index': extensions.get('folder_index', 0) or 0,
        'comment': (extensions.get('properties', {}) or {}).get('comment', ''),
        'value_template': extensions.get('value_raw', ''),
        'loop_over_list': False,
        'list_to_loop': '',
    }
    outcome.update(cmk_conditions_to_outcome(extensions.get('conditions')))
    return outcome


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
            loop_list, error = resolve_loop_list(outcome.list_to_loop, attributes)
            if error:
                results.append(_render_outcome_preview(
                    outcome, attributes,
                    note=(f"loop list '{outcome.list_to_loop}' could not be "
                          f"rendered: {error}"),
                ))
                continue
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

def deep_compare(ours, stored, strict=False):
    """
    Check whether our configured rule value is equivalent to the value
    Checkmk has stored. Asymmetric on dict keys: Checkmk normalises rule
    values on save, often enriching them with schema defaults we did not
    explicitly set. Treating every extra stored key as drift produces an
    endless UPDATE/DELETE churn — so we only require that every key we
    set matches; stored extras are accepted as defaults.

    The price of that tolerance is that a key *removed* from the value
    template reads exactly like a Checkmk-side default and is therefore
    never pushed. ``strict`` (the outcome's ``enforce_value``) drops the
    tolerance and demands identical key sets, so removals are applied —
    at the risk of re-writing the rule on every run when this ruleset is
    one of those Checkmk enriches.

    List items are compared order-insensitive to tolerate reorderings.
    Nested dicts inside lists are still compared structurally via each
    element's ``==``.
    """
    if isinstance(ours, dict) and isinstance(stored, dict):
        ours = clean_postproccessed(ours)
        stored = clean_postproccessed(stored)
        if strict:
            if set(ours.keys()) != set(stored.keys()):
                return False
        elif not set(ours.keys()).issubset(set(stored.keys())):
            return False
        return all(deep_compare(v, stored[k], strict) for k, v in ours.items())
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

class CheckmkRuleSync(CMK2):  # pylint: disable=too-many-instance-attributes
    """
    Export Checkmk Rules
    """
    rulsets_by_type = {}

    # Which account "Plugin Setting" block holds this run's object
    # filter. None = the run's own name. The analysis sets it so it can
    # be logged under its own name and still read the export's filter.
    settings_name = None

    def __init__(self, account=False, probe_version=True):
        super().__init__(account, probe_version=probe_version)
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
        # Rules created during this run, per ruleset, in the order they
        # were POSTed. Checkmk appends a new rule at the bottom of the
        # folder, so together with the captured order this reconstructs
        # where every owned rule currently sits — without a second GET.
        self._created_order_by_ruleset = {}
        # Rulesets whose current state could not be read this run (timeout,
        # Checkmk error). Their create step is skipped as well: without
        # knowing what is already there, creating would duplicate rules.
        self._failed_rulesets = set()
        # Host-independent rules, wired in by inits.export_rules. Evaluated
        # once in calculate_static_rules instead of per host.
        self.static_rules = []
        # Optional Project name scoping the ``rule_marker``.
        # The current export runs are account-wide (all allowed projects in
        # one pass), so this stays None there — it is kept for callers that
        # manage a single project's rules in isolation.
        self.project = None
        # ruleset name -> item_type, fetched once per run by
        # ruleset_item_types(); None until the first lookup needs it.
        self._ruleset_item_types = None
        # (ruleset, condition key) pairs already reported as dropped, so the
        # warning is logged once per run instead of once per host.
        self._dropped_condition_warnings = set()
        # outcome signature -> Setup Rule name, built on first use by
        # _source_rule_name(). None until then.
        self._source_rule_names = None
        # rule_type -> set of content signatures already collected into
        # rulsets_by_type, so the duplicate check does not rescan the list.
        self._rule_signatures = {}
        # ruleset name -> the condition keys Checkmk discards for it. Only
        # depends on the ruleset, and it is asked once per rule per host.
        self._unsupported_conditions = {}

    @property
    def rule_marker(self):
        """
        Description marker written onto every rule this run owns in Checkmk.

        ``clean_rules``/``sort_rules`` only ever touch rules carrying this
        exact marker, so it doubles as the ownership boundary. A per-project
        export scopes the marker with the project name; the global export
        keeps the historical ``cmdbsyncer_{account_id}`` unchanged for
        backwards compatibility.
        """
        if self.project:
            slug = "".join(
                char if char.isalnum() else "_" for char in self.project)
            return f"cmdbsyncer_{self.account_id}_{slug}"
        return f"cmdbsyncer_{self.account_id}"

    def _owns_rule(self, cmk_rule):
        """
        Whether a Checkmk rule belongs to this run.

        The description starts with the ownership marker and continues with
        the Setup Rule's name (see ``_rule_description``), so ownership is a
        prefix test. The separating space keeps a project marker
        (``cmdbsyncer_1_project``) out of the global marker's rules.
        """
        description = cmk_rule['extensions']['properties'].get('description', '')
        return description == self.rule_marker or \
            description.startswith(f"{self.rule_marker} ")

    def _source_rule_name(self, outcome):
        """
        Name of the Setup Rule an outcome was configured in.

        Empty when the outcome cannot be traced back to exactly one rule -
        two rules carrying identical outcomes, or a caller that did not wire
        up any rules at all.
        """
        if self._source_rule_names is None:
            self._source_rule_names = {}
            actions = getattr(self, 'actions', None)
            rules = list(getattr(actions, 'rules', None) or [])
            rules += list(self.static_rules or [])
            for rule in rules:
                for outcome_doc in rule.outcomes:
                    key = outcome_signature(dict(outcome_doc.to_mongo()))
                    known = self._source_rule_names.get(key, rule.name)
                    # Two rules generate the very same outcome: naming one of
                    # them in Checkmk would be a guess, so name neither.
                    self._source_rule_names[key] = \
                        known if known == rule.name else ''
        return self._source_rule_names.get(outcome_signature(outcome), '')

    def _rule_description(self, outcome):
        """
        Description written onto the Checkmk rule: the ownership marker, the
        Setup Rule that created it, and - for a ``keep_value`` outcome - the
        hint that the value may be adjusted right there in Checkmk.
        """
        description = self.rule_marker
        name = self._source_rule_name(outcome)
        if name:
            description += f" - {name[:DESCRIPTION_NAME_LIMIT]}"
        if outcome.get('keep_value'):
            description += f" {KEEP_VALUE_MARK}"
        return description

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


    def ruleset_item_types(self):
        """
        Map every ruleset name of the target Checkmk to its ``item_type``,
        fetched once per run. ``None`` marks a host ruleset (it has no
        service item), anything else ("service" / "item") a service one.

        ``used`` is a filter, not a flag — the full registry is the union of
        ``used=true`` and ``used=false`` (see RulesetCatalog.export_to_file).
        """
        if self._ruleset_item_types is None:
            if getattr(self, 'offline', False):
                # Offline analyses read the shipped ruleset catalog
                # instead of asking Checkmk. It carries the same
                # item_type per ruleset (see checkmk export_rulesets).
                # Imported here: the catalog module is only needed on
                # this path and pulls in the whole plugin package.
                # pylint: disable=import-outside-toplevel
                from application.plugins.checkmk.rulesets_catalog import (
                    item_types_from_files)
                self._ruleset_item_types = item_types_from_files(
                    self.checkmk_version)
                return self._ruleset_item_types
            item_types = {}
            for used in ('true', 'false'):
                try:
                    response, _ = self.request(
                        f"domain-types/ruleset/collections/all?used={used}",
                        method="GET")
                except CmkException as error:
                    self.log_error(
                        f"Could not read the ruleset list from Checkmk: {error}")
                    continue
                for ruleset in response.get('value', []):
                    extensions = ruleset.get('extensions', {}) or {}
                    name = extensions.get('name') or ruleset.get('id')
                    if name:
                        item_types[name] = extensions.get('item_type')
            self._ruleset_item_types = item_types
        return self._ruleset_item_types

    def unsupported_condition_keys(self, ruleset_name):
        """
        Condition keys Checkmk silently discards for ``ruleset_name``.

        Checkmk accepts a rule whose conditions the ruleset does not support
        (HTTP 200) but stores it without them, so the condition is gone on the
        next read. Sending one anyway makes every export delete and recreate
        the rule, because ``clean_rules`` compares the sent condition with the
        stored one and never recognises its own rule again. Verified against
        Checkmk 2.3, 2.4 and 2.5:

        * a host ruleset (``item_type`` is None) drops both service conditions
        * "Service labels" (``service_label_rules``) drops service labels and
          "Host labels" (``host_label_rules``) drops host labels — a ruleset
          that assigns labels cannot match on the labels it assigns

        An unknown ruleset yields nothing: without knowing its type we must
        not strip a condition the admin configured.
        """
        if not ruleset_name:
            return set()
        cached = self._unsupported_conditions.get(ruleset_name)
        if cached is not None:
            return cached
        item_types = self.ruleset_item_types()
        keys = set()
        if ruleset_name in item_types and item_types[ruleset_name] is None:
            keys.update(SERVICE_CONDITION_KEYS)
        if ruleset_name == 'service_label_rules':
            keys.update(SERVICE_LABEL_KEYS)
        if ruleset_name == 'host_label_rules':
            keys.update(HOST_LABEL_KEYS)
        self._unsupported_conditions[ruleset_name] = keys
        return keys

    def drop_unsupported_conditions(self, ruleset_name, condition_tpl,
                                    base_keys):
        """
        Remove the conditions Checkmk would discard for this ruleset from
        ``condition_tpl`` (in place), so what we send is what Checkmk stores.

        Keys the condition template always carries are reset to their empty
        value — Checkmk returns those empty rather than omitting them — while
        keys only present when configured are removed entirely. The admin is
        told once per ruleset and key that the condition has no effect.
        """
        unsupported = self.unsupported_condition_keys(ruleset_name)
        if not unsupported:
            return
        for key in sorted(unsupported):
            if not condition_tpl.get(key):
                continue
            if (ruleset_name, key) not in self._dropped_condition_warnings:
                self._dropped_condition_warnings.add((ruleset_name, key))
                self.log_error(
                    f"Checkmk ignores the '{key}' condition in ruleset "
                    f"'{ruleset_name}', so it is left out of the exported "
                    f"rule. Remove it from the Setup Rule.")
            if key in base_keys:
                condition_tpl[key] = []
            else:
                del condition_tpl[key]

    def list_used_rulesets(self):
        """
        Yield the name of every ruleset that currently holds at least one
        rule. Checkmk has no "all rules in a folder" endpoint, so importing
        a folder means enumerating the used rulesets and then pulling the
        rules of each (see fetch_rules_in_folder).
        """
        response, _ = self.request(
            "domain-types/ruleset/collections/all?used=true", method="GET")
        for ruleset in response.get('value', []):
            extensions = ruleset.get('extensions', {}) or {}
            name = extensions.get('name') or ruleset.get('id')
            if name and extensions.get('number_of_rules', 0):
                yield name

    def fetch_rules_in_folder(self, folder, recursive=False):
        """
        Return every Checkmk rule that lives in ``folder`` (optionally in its
        subfolders), across all used rulesets, as a list of dicts:
        ``{'cmk_id', 'ruleset', 'folder', 'disabled', 'outcome'}`` where
        ``outcome`` is the RuleMngmtOutcome-shaped dict from
        ``cmk_rule_to_outcome``.
        """
        collected = []
        rulesets = list(self.list_used_rulesets())
        with make_progress() as progress:
            task1 = progress.add_task(
                f"Scan {len(rulesets)} rulesets for folder {folder}",
                total=len(rulesets))
            for ruleset_name in rulesets:
                url = ("domain-types/rule/collections/all"
                       f"?ruleset_name={ruleset_name}")
                response, _ = self.request(url, method="GET")
                for cmk_rule in response.get('value', []):
                    extensions = cmk_rule.get('extensions', {}) or {}
                    if not folder_in_scope(
                            extensions.get('folder', '/'), folder, recursive):
                        continue
                    # Ensure the ruleset name is present for the converter
                    # even if the per-rule payload omits it.
                    extensions.setdefault('ruleset', ruleset_name)
                    collected.append({
                        'cmk_id': cmk_rule.get('id'),
                        'ruleset': ruleset_name,
                        'folder': normalize_cmk_folder(
                            extensions.get('folder', '/')),
                        'disabled': (extensions.get('properties', {}) or {})
                                    .get('disabled', False),
                        'outcome': cmk_rule_to_outcome(cmk_rule),
                    })
                progress.advance(task1)
        return collected

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
        # Only set by the optimization analysis. Held aside so it reaches
        # neither the identity hash nor anything Checkmk sees, and put
        # back once the rule is fully built.
        syncer_rule = rule_params.pop('_syncer_rule', None)
        syncer_outcome = rule_params.pop('_syncer_outcome', None)
        # Before any template is rendered or dropped: the outcome is still in
        # the shape the rule document stores it, which is what identifies the
        # Setup Rule it came from.
        rule_params['description'] = self._rule_description(rule_params)

        # Setup condition template based on Checkmk version
        if self.checkmk_version.startswith('2.2'):
            condition_tpl = {"host_tags": [], "service_labels": []}
        else:
            condition_tpl = {"host_tags": [], "service_label_groups": [],
                             "host_label_groups": []}
        # Keys the template always carries. Checkmk returns those empty
        # instead of omitting them, which decides how an unsupported
        # condition has to be cleared (see drop_unsupported_conditions).
        base_condition_keys = set(condition_tpl)

        # Prepare context for Jinja rendering. The copy exists only to
        # carry the loop variables — nothing below writes to the context,
        # so without them the host's attribute dict is handed over as it is
        # instead of being duplicated once per rule and host.
        if loop_value is not None:
            context = dict(attributes['all'])
            context['loop'] = loop_value
            context['loop_idx'] = loop_idx
        else:
            context = attributes['all']

        # Render value and folder
        value = render_jinja(rule_params['value_template'], _ctx=context)
        rule_params['folder'] = normalize_folder(
            render_jinja(rule_params['folder'], _ctx=context))
        # Respect the account's folder scope (limit_by_folders): a scoped
        # account only receives rules whose target folder is in scope, just
        # like the host export only pushes hosts of those folders. A rule
        # assigned to a Project is exempt — it is routed by the project's
        # account lists (see projects_for_account), so the folder scope only
        # gates project-less (global) rules. The marker is dropped afterwards
        # so it never reaches the Checkmk payload.
        rule_project = rule_params.pop('project', None)
        if not rule_project and not folder_within_scope(
                rule_params['folder'], self.config.get('limit_by_folders')):
            return None
        rule_params['value'] = value
        del rule_params['value_template']
        rule_params['optimize'] = False

        # When the outcome opts into keeping a manually adjusted value, tell the
        # operator right in the Checkmk rule comment that the Syncer will not
        # overwrite it. The hint is part of the comment everywhere (create and
        # the clean_rules compare), so it stays a stable identification key.
        if rule_params.get('keep_value'):
            base_comment = (rule_params.get('comment') or '').strip()
            if KEEP_VALUE_HINT not in base_comment:
                rule_params['comment'] = (
                    f"{base_comment}\n{KEEP_VALUE_HINT}".strip())

        # Handle condition_label_template (Host label)
        if not self._apply_host_label_condition(rule_params, condition_tpl, context):
            return None  # skip this rule — malformed label reported already

        # Handle condition_service (legacy support)
        if 'condition_service' in rule_params:
            if rule_params['condition_service']:
                service_condition = render_jinja(
                    rule_params['condition_service'], _ctx=context)
                condition_tpl['service_description'] = {
                    "match_on": get_list(service_condition),
                    "operator": "one_of"
                }
            del rule_params['condition_service']

        # Handle condition_service_label (Service labels)
        if not self._apply_service_label_condition(rule_params, condition_tpl, context):
            return None  # skip this rule — malformed label reported already

        # Drop what Checkmk would silently discard for this ruleset, so the
        # rule we send is the rule Checkmk stores — otherwise clean_rules
        # never recognises it again and every run deletes and recreates it.
        self.drop_unsupported_conditions(
            rule_params.get('ruleset'), condition_tpl, base_condition_keys)
        # Evaluated after the drop: a host-label condition Checkmk discards
        # must not keep the per-host "optimize" coalescing from kicking in.
        has_hostlabel_condition = bool(
            condition_tpl.get('host_label_groups') or condition_tpl.get('host_labels'))

        # Handle condition_host. It's always at the end to calculate correct
        # identification hash of entry
        if rule_params.get('condition_host'):
            host_condition = render_jinja(
                rule_params['condition_host'], _ctx=context)
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
        if syncer_rule is not None:
            rule_params['_syncer_rule'] = syncer_rule
            rule_params['_syncer_outcome'] = syncer_outcome
        return rule_params

    def _apply_host_label_condition(self, rule_params, condition_tpl, context):
        """
        Add the Host label condition to ``condition_tpl`` in place and drop
        the source key from ``rule_params``. Returns False when the rendered
        label is not a single 'key:value' (the caller then skips the rule),
        True otherwise — including when no condition is configured.
        """
        template = rule_params.pop('condition_label_template', None)
        if not template:
            return True
        rendered = render_jinja(template, _ctx=context)
        parsed = parse_label(rendered)
        if not parsed:
            self.log_error(
                f"Skipped a Checkmk rule for '{context['HOSTNAME']}': the Host label "
                f"condition must render to a single 'key:value', got '{rendered}'"
            )
            return False
        label_key, label_value = parsed
        if self.checkmk_version.startswith('2.2'):
            condition_tpl['host_labels'] = [{
                "key": label_key, "operator": "is", "value": label_value,
            }]
        else:
            condition_tpl['host_label_groups'] = [{
                "operator": "and",
                "label_group": [{
                    "operator": "and",
                    "label": f"{label_key}:{label_value}",
                }],
            }]
        return True

    def _apply_service_label_condition(self, rule_params, condition_tpl, context):
        """
        Add the Service label condition to ``condition_tpl`` in place and drop
        the source key from ``rule_params``. Every comma-separated entry must
        be a 'key:value' label (they are AND-combined). Returns False when any
        entry is malformed (the caller then skips the rule), True otherwise —
        including when no condition is configured.
        """
        if 'condition_service_label' not in rule_params:
            return True
        template = rule_params.pop('condition_service_label')
        if not template:
            return True
        labels = []
        for entry in get_list(render_jinja(template, _ctx=context)):
            parsed = parse_label(entry)
            if not parsed:
                self.log_error(
                    f"Skipped a Checkmk rule for '{context['HOSTNAME']}': Service "
                    f"label conditions must be 'key:value', got '{entry}'"
                )
                return False
            labels.append(f"{parsed[0]}:{parsed[1]}")
        condition_tpl['service_label_groups'] = [{
            "label_group": [{"operator": "and", "label": x} for x in labels],
            "operator": "and",
        }]
        return True

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
            self.rulsets_by_type[rule_type] = self._dedupe_identical_rules(
                final_rules)

    @staticmethod
    def _dedupe_identical_rules(rules):
        """
        Drop rules that are identical in every field that actually reaches
        Checkmk (folder, comment, condition, value).

        The same logical rule can be generated twice when a
        ``CheckmkRuleMngmt`` matches ``anyway`` but pins a static
        ``condition_host``: the host whose ``HOSTNAME`` equals that name
        takes the optimize path (its dict carries the transient
        ``optimize`` / ``optimize_rule_hash`` bookkeeping keys), while every
        other host produces the plain variant. Both describe one and the
        same Checkmk rule, but the differing bookkeeping defeats the
        ``not in`` guard in ``calculate_rules_of_host`` — so Checkmk ended
        up with two identical rules. Keying on content alone removes the
        duplicate while preserving genuinely distinct rules (e.g. a
        coalesced multi-host condition vs. a single-host one).
        """
        seen = set()
        deduped = []
        for rule in rules:
            signature = json.dumps(
                {
                    'folder': rule.get('folder', '/'),
                    'comment': rule.get('comment', ''),
                    'value': rule.get('value', ''),
                    'condition': rule.get('condition', {}),
                },
                sort_keys=True, default=repr,
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(rule)
        return deduped



    def export_cmk_rules(self):
        """
        Export config rules to checkmk
        """
        self.calculate_rules()
        self.calculate_static_rules()
        self.optimize_rules()
        self._sort_rulsets_by_intent()
        self.clean_rules()
        self.clean_orphaned_rules()
        self.create_rules()
        self.sort_rules()

    def _export_hosts(self):
        """
        The hosts this run generates rules for. Honors the account's
        object filter, and otherwise stays on the host-only default.
        """
        # The analysis logs under its own name but has to read the object
        # filter the export is configured with. And .get all the way
        # down: without an account there is no settings block at all.
        settings_key = self.settings_name or self.name
        object_filter = self.config.get(
            'settings', {}).get(settings_key, {}).get('filter')
        if not object_filter:
            # Default/ Legacy Behavior. Exclude CMDB template objects:
            # they are label vehicles for real hosts (applied via
            # ``cmdb_templates``) and have no business showing up as
            # condition_host targets — Jinja-rendering ``{{HOSTNAME}}``
            # against a template would otherwise create a rule pointing
            # at the template's name (and a folder derived from its
            # labels), which never matches any real host in CMK.
            return Host.active_non_template()
        return Host.objects_by_filter(object_filter)

    def calculate_rules(self, use_cache=True):
        """
        Render every rule the run generates, per host, into
        ``rulsets_by_type``. Shared by the export and by the
        optimization analysis so both judge the same rule set.

        ``use_cache=False`` bypasses the per-host outcome cache: the
        analysis has to see the rules as they are configured right now,
        and must not write its own tagged outcomes into the cache the
        export reads.
        """
        print(f"\n{CC.HEADER}Build needed Rules{CC.ENDC}")
        print(f"{CC.OKGREEN} -- {CC.ENDC} Loop over Hosts and collect distinct rules")
        db_objects = self._export_hosts()
        total = db_objects.count()
        with make_progress() as progress:
            task1 = progress.add_task("Calculate rules", total=total)
            for db_host in db_objects:
                # persist_cache=False + one flush: the attribute and
                # outcome caches are filled in five steps, and saving the
                # host after each of them meant five writes per host.
                attributes = self.get_attributes(db_host, 'checkmk',
                                                 persist_cache=False)
                if not attributes:
                    logger.debug("Skipped: %s", db_host.hostname)
                    self.flush_host_cache(db_host)
                    progress.advance(task1)
                    continue
                # self.actions is injected by the inits.export_rules wiring
                host_actions = self.actions.get_outcomes(  # pylint: disable=no-member
                    db_host, attributes['all'], persist_cache=False,
                    use_cache=use_cache)
                self.flush_host_cache(db_host)
                if host_actions:
                    self.calculate_rules_of_host(host_actions, attributes)
                progress.advance(task1)

    def _optimized_rule_groups(self):
        """
        The host groups ``optimize_rules`` would coalesce into one rule:
        ``{(ruleset, hash): {'rule': …, 'hosts': {hostname, …}}}``.

        Call after ``calculate_rules`` and before ``optimize_rules`` —
        afterwards the per-host entries are already merged away.
        """
        groups = {}
        for ruleset_name, rules in self.rulsets_by_type.items():
            for rule in rules:
                if not rule.get('optimize'):
                    continue
                key = (ruleset_name, rule['optimize_rule_hash'])
                group = groups.setdefault(
                    key, {'rule': rule, 'hosts': set(), 'syncer_rules': set()})
                group['hosts'].update(condition_hosts(rule['condition']))
                source = rule.get('_syncer_rule')
                if source:
                    group['syncer_rules'].add(
                        (source, rule.get('_syncer_outcome')))
        return groups

    def _outcome_rule_census(self):
        """
        How many distinct Checkmk rules every Setup Rule outcome produced:
        ``{(syncer_rule, outcome_index): {rule identity, …}}``.

        A single outcome is not necessarily a single rule. Its value is
        rendered per host, so an outcome whose value carries the host's
        own contact group produces one rule per contact group — each with
        its own host list, each looking perfectly replaceable on its own.
        The outcome has exactly one condition though, so giving it one
        group's label hands that condition to all the other groups too,
        and every host carrying the label collects every rendered value.
        Counting the rules per outcome is what tells the two cases apart.

        Call after ``calculate_rules`` and before ``optimize_rules``.
        """
        census = {}
        for ruleset_name, rules in self.rulsets_by_type.items():
            for rule in rules:
                source = rule.get('_syncer_rule')
                if not source:
                    continue
                if rule.get('optimize'):
                    identity = (ruleset_name, rule['optimize_rule_hash'])
                else:
                    # Not coalesced: the same outcome can still emit this
                    # rule for many hosts, so identify it by what reaches
                    # Checkmk instead of by host.
                    identity = (ruleset_name, str(rule.get('folder')),
                                str(rule.get('condition')),
                                str(rule.get('value')))
                outcome = (source, rule.get('_syncer_outcome'))
                census.setdefault(outcome, set()).add(identity)
        return census

    @staticmethod
    def _host_label_set(attributes):
        """
        The host's attributes as a set of hashable ``key:value`` pairs,
        rendered the way the host export writes them as Checkmk labels —
        a suggested condition has to match what Checkmk actually stores.

        Anything that cannot serve as a single label value is left out
        rather than suggested: containers, comma-separated lists, values
        carrying whitespace, wildcards or service/regex patterns.
        """
        lowercase = app.config.get('CMK_LOWERCASE_LABEL_VALUES')
        labels = set()
        for key, value in (attributes or {}).items():
            key = str(key)
            if not _usable_as_label(key):
                continue
            if isinstance(value, (dict, list, tuple, set)):
                if value:
                    labels.add((f"{key}{HASHED_LABEL_SUFFIX}",
                                syncer_hash(value), key))
                continue
            # The export writes ``str(value).replace(':', '-')``, plus the
            # optional lowercasing — see CheckmkHostSync.
            raw = str(value)
            value = raw.replace(':', '-')
            if lowercase:
                value = value.lower()
            if not value.strip():
                continue
            if _usable_as_label(value) and len(value) <= MAX_LABEL_VALUE_LEN:
                labels.add((key, value, None))
            else:
                # A comma list, a value with spaces, a service pattern, a
                # long dump: unusable as a label itself, but a hash of it
                # is — and it groups exactly the same hosts.
                labels.add((f"{key}{HASHED_LABEL_SUFFIX}",
                            syncer_hash(raw), key))
        return labels

    def _collect_label_coverage(self, groups):
        """
        Count, for every candidate label, how often it occurs inside each
        group and across the whole export scope.

        The per-group count tells whether a label covers the group; the
        difference to the total tells whether it would drag in hosts the
        rule does not currently apply to. One pass, only counters — an
        inverted index of host names would not survive a large inventory.
        """
        totals = Counter()
        per_group = {key: Counter() for key in groups}
        # Which attribute names survive the export filter — those are the
        # ones Checkmk sees as a host label. An attribute that does not
        # get through can still be suggested; it just has to be let
        # through first, and the report says so.
        exported_keys = set()
        print(f"{CC.OKGREEN} -- {CC.ENDC} Collect labels of all hosts")
        db_objects = self._export_hosts()
        with make_progress() as progress:
            task1 = progress.add_task("Collect labels",
                                      total=db_objects.count())
            for db_host in db_objects:
                attributes = self.get_attributes(db_host, 'checkmk',
                                                 persist_cache=False)
                self.flush_host_cache(db_host)
                progress.advance(task1)
                if not attributes:
                    continue
                labels = self._host_label_set(attributes['all'])
                totals.update(labels)
                exported_keys.update(attributes.get('filtered') or {})
                for key, group in groups.items():
                    if db_host.hostname in group['hosts']:
                        per_group[key].update(labels)
        return totals, per_group, exported_keys

    @staticmethod
    def _suggest_labels_for_group(hosts, group_counter, totals):
        """
        Rank the labels that could replace a group's host list.

        ``exact``   — every host of the group carries it, no other host does.
        ``wider``   — covers the group, but more hosts would match too.
        ``partial`` — no host outside carries it, but it misses some of
                      the group's hosts.
        """
        size = len(hosts)
        exact, wider, partial = [], [], []
        for label, inside in group_counter.items():
            outside = totals[label] - inside
            if inside == size and not outside:
                exact.append((label, inside, outside))
            elif inside == size:
                wider.append((label, inside, outside))
            elif not outside and inside >= size * PARTIAL_LABEL_COVERAGE:
                partial.append((label, inside, outside))
        # Fewest surprises first: a wider label that pulls in two hosts
        # beats one that pulls in two hundred, and a partial label that
        # misses the least is the closest to the current rule.
        wider.sort(key=lambda entry: entry[2])
        partial.sort(key=lambda entry: -entry[1])
        return exact, wider, partial

    def analyse_rule_optimization(self, min_hosts=10, top=20, apply=False,
                                  hash_labels=False):
        """
        Report which rules were built from a long list of host names and
        which host label could take its place.

        A rule that names hundreds of hosts is rewritten on every host
        that joins or leaves it, is unreadable in Checkmk and slow to
        match. Usually the hosts share a label already — this finds it.
        """
        self.actions.tag_source_rule = True  # pylint: disable=no-member
        self.calculate_rules(use_cache=False)
        groups = {key: group for key, group in
                  self._optimized_rule_groups().items()
                  if len(group['hosts']) >= min_hosts}
        print(f"\n{CC.HEADER}Analyse Rule Optimization{CC.ENDC}")
        if not groups:
            print(f"{CC.OKGREEN}  ** {CC.ENDC}No rule is built from "
                  f"{min_hosts} or more host names — nothing to optimize")
            return []
        ranked = sorted(groups.items(),
                        key=lambda item: -len(item[1]['hosts']))
        if len(ranked) > top:
            print(f"{CC.WARNING}  ** {CC.ENDC}{len(ranked)} rules qualify, "
                  f"reporting the {top} largest (raise with --top)")
            ranked = ranked[:top]
        selected = dict(ranked)
        census = self._outcome_rule_census()
        totals, per_group, exported_keys = \
            self._collect_label_coverage(selected)
        results = []
        for key, group in ranked:
            hosts = group['hosts']
            exact, wider, partial = self._suggest_labels_for_group(
                hosts, per_group[key], totals)
            # Checkmk stores a rule of some rulesets without its host
            # label condition (a ruleset that assigns host labels cannot
            # match on them). Swapping the host list for a label there
            # would leave the rule with no condition at all — it would
            # apply to every host in the folder.
            label_condition_kept = not set(HOST_LABEL_KEYS).intersection(
                self.unsupported_condition_keys(key[0]))
            # How many Checkmk rules the outcome behind this group feeds.
            # More than one means its condition is shared, and swapping
            # it for this group's label would change the others too.
            outcome_rules = max(
                (len(census.get(outcome, ())) for outcome
                 in group['syncer_rules']), default=1)
            results.append({
                'ruleset': key[0],
                'label_condition_kept': label_condition_kept,
                'outcome_rules': outcome_rules,
                'rule': group['rule'],
                'syncer_rules': sorted(group['syncer_rules']),
                'hosts': len(hosts),
                'exact': exact,
                'wider': wider,
                'partial': partial,
                'exported_keys': exported_keys,
            })
        self._print_optimization_report(results)
        if apply:
            self.apply_findings(results, hash_labels)
        else:
            replaceable = sum(1 for result in results if result['exact'])
            if replaceable:
                print(f"{CC.OKCYAN}  ** {CC.ENDC}Re-run with --apply to "
                      "change those Setup Rules for you")
        return results

    def _print_optimization_report(self, results):
        """
        Print the analysis as a work list on the Syncer rules: which rule
        to open, and what to put into its outcome so the export stops
        building a condition out of host names.
        """
        for result in results:
            rule = result['rule']
            names = ", ".join(
                name for name, _index in result['syncer_rules']) or '<unknown>'
            print(f"\n{CC.OKBLUE} * {CC.ENDC}Setup Rule "
                  f"{CC.BOLD}{names}{CC.ENDC} — "
                  f"{result['hosts']} hosts end up in one condition")
            print(f"   ruleset: {result['ruleset']}   "
                  f"folder: {rule.get('folder', '/')}")
            if rule.get('comment'):
                print(f"   comment: {rule['comment'].splitlines()[0]}")
            print(f"   value:   {shorten_value(rule.get('value', ''))}")
            if result['exact'] and not result['label_condition_kept']:
                print(f"{CC.FAIL}   !! {CC.ENDC}Checkmk discards host label "
                      f"conditions in ruleset {result['ruleset']}, so a "
                      "label cannot replace the host list here — the rule "
                      "would end up matching every host")
                continue
            if result['exact'] and result.get('outcome_rules', 1) > 1:
                print(f"{CC.FAIL}   !! {CC.ENDC}This outcome produces "
                      f"{result['outcome_rules']} different Checkmk rules "
                      "(its outcome is rendered per host) but has only one "
                      "condition — a label here would apply to the other "
                      "rules as well, and every host carrying it would "
                      "collect all of their values. Leave the host list, or "
                      "split the outcome per group first")
                continue
            for label, _inside, _outside in result['exact']:
                key, value, source = label
                print(f"{CC.OKGREEN}   -> in the outcome set Condition Label "
                      f"to {key}:{value} and clear Condition Host"
                      f"{CC.ENDC} — covers all {result['hosts']} hosts "
                      "and no other host")
                if source:
                    print(f"{CC.OKCYAN}      {CC.ENDC}'{source}' is no usable "
                          f"label on its own, so {key} is a hash of it — "
                          f"needs a Rewrite rule adding "
                          f"{key} = {{{{ {source} | hash }}}}")
                if key not in result['exported_keys']:
                    print(f"{CC.WARNING}      note{CC.ENDC}: "
                          f"'{key}' does not pass the export filter, so "
                          "Checkmk never sees it as a host label — it has "
                          "to be let through first")
            for label, _inside, outside in result['wider'][:3]:
                print(f"{CC.OKCYAN}   ~  {label[0]}:{label[1]}{CC.ENDC} covers "
                      f"all {result['hosts']} hosts, but {outside} more "
                      "host(s) would get the rule too")
            for label, inside, _outside in result['partial'][:3]:
                print(f"{CC.OKCYAN}   ~  {label[0]}:{label[1]}{CC.ENDC} covers "
                      f"{inside} of {result['hosts']} hosts, no other host "
                      f"— {result['hosts'] - inside} would lose the rule")
            if not (result['exact'] or result['wider'] or result['partial']):
                print(f"{CC.WARNING}   !! {CC.ENDC}No label comes close; "
                      "these hosts share nothing the others do not. "
                      "A label set by a Rewrite rule would do it.")
        replaceable = sum(1 for result in results if result['exact'])
        print(f"\n{CC.HEADER}  ** {CC.ENDC}{replaceable} of {len(results)} "
              "reported Setup Rule(s) can be switched to a single "
              "Host label condition")

    def _apply_finding(self, result, hash_labels=False):
        """
        Rewrite one Setup Rule outcome to use the suggested label instead
        of a host condition, and let the attribute through the export
        filter if it does not pass it yet.

        Returns a status string for the report, or None when the finding
        is not safe to apply on its own.
        """
        # pylint: disable=import-outside-toplevel
        from application.plugins.checkmk.models import (
            CheckmkRuleMngmt, CheckmkFilterRule)
        if not result['exact']:
            return None
        blocker = self._reason_not_to_apply(result)
        if blocker:
            return blocker
        rule_name, outcome_index = result['syncer_rules'][0]
        # Every exact label covers the same hosts, so any of them is
        # correct — pick the first by name so re-runs are stable, and
        # name the alternatives in the report.
        labels = sorted(label for label, _inside, _outside in result['exact'])
        key, value, source = labels[0]
        if hash_labels and not source and key not in result['exported_keys']:
            # The attribute would have to be let through the filter, and
            # the operator does not want its raw values in Checkmk. Match
            # on a hash of it instead — same grouping, nothing readable.
            source, key = key, f"{key}{HASHED_LABEL_SUFFIX}"
            value = syncer_hash(value)
        try:
            rule = CheckmkRuleMngmt.objects.get(name=rule_name)
        except DoesNotExist:
            return f"Setup Rule '{rule_name}' no longer exists"
        try:
            outcome = rule.outcomes[outcome_index]
        except IndexError:
            return f"Setup Rule '{rule_name}' has no outcome {outcome_index}"
        outcome.condition_label_template = f"{key}:{value}"
        outcome.condition_host = ''
        rule.save()
        done = [f"condition is now the label {key}:{value}"]
        if source:
            done.append(self._add_hash_rewrite(key, source, hash_labels))
        if key not in result['exported_keys']:
            done.append(self._whitelist_attribute(CheckmkFilterRule, key))
        if len(labels) > 1:
            others = ", ".join(f"{other[0]}:{other[1]}"
                               for other in labels[1:])
            done.append(f"equally exact alternatives were {others}")
        return "; ".join(done)

    @staticmethod
    def _add_hash_rewrite(label_key, source_key, transform=False):
        """
        Add the Rewrite rule outcome that produces the hashed attribute
        the condition matches on: ``<source>_hash = {{ <source> | hash }}``.

        Written as a new attribute rather than a rename, so the original
        value stays available to every other rule. A host that does not
        carry the source attribute gets nothing — the Jinja render
        nullifies and the rewrite engine skips an empty value.
        """
        # pylint: disable=import-outside-toplevel
        from application.plugins.checkmk.models import (
            CheckmkRewriteAttributeRule)
        from application.modules.rule.models import AttributeRewriteAction
        rule = CheckmkRewriteAttributeRule.objects(
            name=APPLY_REWRITE_RULE_NAME).first()
        if not rule:
            rule = CheckmkRewriteAttributeRule()
            rule.name = APPLY_REWRITE_RULE_NAME
            rule.documentation = (
                "Created by 'checkmk analyse_rules --apply'. Provides a "
                "hashed copy of attributes whose value cannot be a "
                "Checkmk label, so a rule can still match on them.")
            rule.condition_typ = 'anyway'
            rule.conditions = []
            rule.outcomes = []
            rule.enabled = True
        if any(outcome.old_attribute_name == label_key
               for outcome in rule.outcomes):
            return f"'{label_key}' is already built by rule {rule.name}"
        action = AttributeRewriteAction()
        action.old_attribute_name = label_key
        action.overwrite_name = ''
        action.new_attribute_name = ''
        action.overwrite_value = 'jinja'
        action.new_value = f"{{{{ {source_key}{_hash_template_filters(transform)} }}}}"
        rule.outcomes.append(action)
        rule.save()
        return (f"'{label_key}' is now built from '{source_key}' by rule "
                f"{rule.name}")

    @staticmethod
    def _reason_not_to_apply(result):
        """
        Why this finding must not be rewritten automatically, or None
        when it is a straight swap.
        """
        if not result.get('label_condition_kept', True):
            return ("Checkmk discards host label conditions in ruleset "
                    f"{result['ruleset']}, not touched")
        if len(result['syncer_rules']) != 1:
            return ("several Setup Rules produce this condition, "
                    "not touched")
        outcome_rules = result.get('outcome_rules', 1)
        if not outcome_rules:
            return ("this finding comes from an older analysis that did not "
                    "check how many rules the outcome feeds — run the "
                    "analysis again")
        if outcome_rules > 1:
            return (f"this Setup Rule outcome produces {outcome_rules} "
                    "different Checkmk rules — its outcome is rendered per "
                    "host, and the outcome has only one condition, so this "
                    "group's label would end up on the other rules too, "
                    "not touched")
        if result['syncer_rules'][0][1] is None:
            return "outcome unknown, not touched"
        return None

    @staticmethod
    def _whitelist_attribute(filter_model, key):
        """
        Make sure ``key`` reaches Checkmk as a host label by whitelisting
        it in a filter rule the analysis owns. Collected in one rule so
        repeated runs extend it instead of littering the rule list.
        """
        # pylint: disable=import-outside-toplevel
        from application.modules.rule.models import FilterAction
        rule = filter_model.objects(name=APPLY_FILTER_RULE_NAME).first()
        if not rule:
            rule = filter_model()
            rule.name = APPLY_FILTER_RULE_NAME
            rule.documentation = (
                "Created by 'checkmk analyse_rules --apply'. Lets the "
                "attributes through that Setup Rule conditions match on.")
            rule.condition_typ = 'anyway'
            rule.conditions = []
            rule.outcomes = []
            rule.enabled = True
        already = {outcome.attribute_name for outcome in rule.outcomes
                   if outcome.action == 'whitelist_attribute'}
        if key in already:
            return f"'{key}' already passes filter rule {rule.name}"
        action = FilterAction()
        action.action = 'whitelist_attribute'
        action.attribute_name = key
        rule.outcomes.append(action)
        rule.save()
        return f"'{key}' whitelisted in filter rule {rule.name}"

    def apply_findings(self, results, hash_labels=False):
        """
        Apply every finding that is a straight swap: the label covers
        exactly the hosts of the rule, so the export keeps producing the
        same rule for the same hosts — just with a short condition.

        ``wider`` and ``partial`` suggestions change which hosts get the
        rule and are never applied automatically.
        """
        print(f"\n{CC.HEADER}Apply findings{CC.ENDC}")
        applied = 0
        for result in results:
            status = self._apply_finding(result, hash_labels)
            if status is None:
                continue
            names = ", ".join(name for name, _i in result['syncer_rules'])
            if result['exact']:
                applied += 1
                print(f"{CC.OKGREEN}  ** {CC.ENDC}{names}: {status}")
            else:
                print(f"{CC.WARNING}  ** {CC.ENDC}{names}: {status}")
        if applied:
            # The outcomes computed from the old conditions are cached on
            # every host — same as a rule edit in the web interface.
            Host.objects(cache__ne={}).update(set__cache={})
            print(f"{CC.OKGREEN}  ** {CC.ENDC}{applied} Setup Rule(s) "
                  "changed, host caches dropped")
        else:
            print(f"{CC.WARNING}  ** {CC.ENDC}Nothing was safe to apply "
                  "on its own")
        return applied

    @staticmethod
    def _rule_signature(rule):
        """
        Content key of a built rule, used to keep ``rulsets_by_type`` free
        of duplicates.
        """
        return json.dumps(rule, sort_keys=True, default=repr)

    def _collect_rule(self, rule_type, updated_rule):
        """
        Append a built rule to ``rulsets_by_type[rule_type]`` unless an
        identical one is already there.

        The duplicate check runs against a set of content signatures, not
        against the list itself: every host contributes rules to the same
        list, and a ``not in`` scan over it compares the new rule with
        every rule collected so far. That is quadratic in the number of
        rules, which stayed unnoticed while a rule meant one entry per
        host and turned "Loop over Hosts and collect distinct rules" into
        minutes as soon as a looping outcome multiplies that by the length
        of its list.
        """
        if updated_rule is None:
            return
        rules = self.rulsets_by_type.setdefault(rule_type, [])
        # The index is seeded from whatever the list already holds and
        # re-seeded whenever the list was replaced or written to from
        # somewhere else (rulsets_by_type is a class attribute, and
        # optimize_rules swaps whole lists), so it can never claim a rule
        # the list does not actually contain.
        cached = self._rule_signatures.get(rule_type)
        if cached is None or cached[0] is not rules or cached[2] != len(rules):
            cached = [rules, {self._rule_signature(rule) for rule in rules}, len(rules)]
            self._rule_signatures[rule_type] = cached
        signature = self._rule_signature(updated_rule)
        if signature in cached[1]:
            return
        cached[1].add(signature)
        rules.append(updated_rule)
        cached[2] = len(rules)

    def calculate_rules_of_host(self, host_actions, attributes):
        """
        Calculate rules by Attribute of Host
        """
        for rule_type, rules in host_actions.items():
            for rule_params in rules:
                # loop_over_list without a list attribute name is a
                # meaningless toggle (e.g. accidentally ticked in the
                # form) — treat it like a plain rule instead of failing
                # on the empty attribute lookup.
                if rule_params.get('loop_over_list') and \
                        rule_params.get('list_to_loop'):
                    loop_list, error = resolve_loop_list(
                        rule_params['list_to_loop'], attributes['all'])
                    if error:
                        self.log_error(
                            f"Loop list '{rule_params['list_to_loop']}' of "
                            f"{rule_params.get('ruleset')} could not be "
                            f"rendered: {error}")
                        continue
                    for loop_idx, loop_value in enumerate(loop_list):
                        loop_rule_params = dict(rule_params)
                        loop_rule_params.pop('loop_over_list', None)
                        loop_rule_params.pop('list_to_loop', None)
                        updated_rule = self.build_condition_and_update_rule_params(
                            loop_rule_params, attributes, loop_value, loop_idx
                        )
                        self._collect_rule(rule_type, updated_rule)
                else:
                    updated_rule = self.build_condition_and_update_rule_params(
                        rule_params, attributes
                    )
                    self._collect_rule(rule_type, updated_rule)



    def calculate_static_rules(self):
        """
        Evaluate host-independent rules exactly once.

        A rule flagged ``static_rule`` carries no host data: its outcome
        templates and conditions never reference host attributes, so it
        resolves to the same Checkmk rule(s) regardless of host. Rendering
        it a single time against an empty attribute context — instead of
        once per host, leaning on de-duplication to collapse the N
        identical copies — skips the whole per-host Jinja/condition pass
        for these rules on large inventories. The rule's match conditions
        are intentionally ignored; a static rule is always emitted.
        """
        if not self.static_rules:
            return
        print(f"{CC.OKGREEN} -- {CC.ENDC} Calculate static (host-independent) rules")
        # HOSTNAME is explicitly None so the per-host "optimize" coalescing
        # in build_condition_and_update_rule_params never triggers — a
        # static rule targets whatever its condition_host literally names,
        # not "this host".
        attributes = {'all': {'HOSTNAME': None}}
        for rule in self.static_rules:
            host_actions = {}
            # Static rules skip the engine's add_outcomes, so stamp the
            # project here too — a static project rule must ignore the
            # account's folder scope like every other project rule.
            rule_project = getattr(rule, 'project', None)
            for outcome in rule.outcomes:
                outcome = dict(outcome.to_mongo())
                if rule_project:
                    outcome['project'] = rule_project
                if outcome.get('loop_over_list') and \
                        outcome.get('list_to_loop'):
                    # loop_over_list iterates a *host* attribute list, which
                    # a static rule by definition does not have. Skip it
                    # rather than fail on the missing attribute. The bare
                    # flag without a list name (accidentally ticked in the
                    # form) is meaningless — such outcomes are exported as
                    # plain rules instead of silently vanishing.
                    # log_error: recorded in the run's log entry AND printed
                    # on the CLI — buried only in the web log it reads like
                    # the rule silently never exports.
                    self.log_error(
                        f"Static rule '{rule.name}' outcome for "
                        f"{outcome.get('ruleset')} uses loop_over_list, "
                        f"which needs host data — skipped")
                    continue
                host_actions.setdefault(outcome['ruleset'], []).append(outcome)
            if host_actions:
                self.calculate_rules_of_host(host_actions, attributes)

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

    def _plan_rule_moves(self):
        """
        Work out which rules have to be moved, before sending anything.

        Returns ``[(ruleset, rule_id, after_rule_id), …]``. Planning up
        front is what makes the progress bar honest: the reorder is one
        request per move, and a big ruleset used to sit on a bar that
        only advanced once the whole chain was through.
        """
        planned = []
        for ruleset_name, rules in self.rulsets_by_type.items():
            if len(rules) < 2:
                continue
            # folder_index defaults to 0; if no rule in this ruleset
            # has an explicit folder_index > 0, the admin has not
            # configured an order — leave the Checkmk-side ordering
            # untouched instead of chaining a move per rule.
            if not any(r.get('folder_index', 0) for r in rules):
                continue
            desired_ids = self._desired_cmk_id_chain(rules)
            if len(desired_ids) < 2:
                continue
            # Skip the move chain when CMK already lists the
            # syncer-owned rules in the desired order.
            if self._is_already_sorted(ruleset_name, rules, desired_ids):
                continue
            current_order = self._current_owned_order(ruleset_name,
                                                      desired_ids)
            if current_order is None:
                indices = range(1, len(desired_ids))
            else:
                indices = self._moves_needed(desired_ids, current_order)
            for index in indices:
                planned.append((ruleset_name, desired_ids[index],
                                desired_ids[index - 1]))
        return planned

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

        Set the account option ``skip_rule_reorder`` to leave the
        Checkmk-side order alone entirely — every move is a write plus
        a pending change, and on a large ruleset that is the slowest
        part of the export by far.
        """
        if self.config.get('skip_rule_reorder'):
            print(f"{CC.OKGREEN} -- {CC.ENDC} Reorder skipped "
                  "(skip_rule_reorder is set on the account)")
            return
        print(f"{CC.OKGREEN} -- {CC.ENDC} Reorder syncer rules")
        planned = self._plan_rule_moves()
        if not planned:
            print(f"{CC.OKGREEN}  ** {CC.ENDC}Every ruleset is already in "
                  "the configured order")
            return
        rulesets = len({entry[0] for entry in planned})
        print(f"{CC.OKBLUE}  * {CC.ENDC}{len(planned)} rule(s) to move "
              f"across {rulesets} ruleset(s)")
        with make_progress() as progress:
            # One step per move, not per ruleset: a single ruleset can
            # hold hundreds of moves, and a bar that only ticks when it
            # is finished looks like the export has hung.
            task1 = progress.add_task("Move rules", total=len(planned))
            for ruleset_name, rule_id, after_id in planned:
                move_url = f"objects/rule/{rule_id}/actions/move/invoke"
                payload = {
                    "position": "after_specific_rule",
                    "rule_id": after_id,
                }
                try:
                    self.request(move_url, data=payload, method="POST")
                    self.log_details.append((
                        "INFO",
                        f"Reordered rule in {ruleset_name}: "
                        f"{rule_id} after {after_id}",
                    ))
                except CmkException as error:
                    self.log_error(
                        f"Could not reorder rule {rule_id} in "
                        f"{ruleset_name}: {error}")
                except Exception as error:  # pylint: disable=broad-except
                    # A non-CmkException (timeout, network reset, JSON
                    # decode, …) used to bubble out of sort_rules and
                    # silently abort the rest of the reorder. Catch it
                    # explicitly so the run continues and the failure
                    # is visible on stdout and in the run log.
                    self.log_error(
                        f"Unexpected error reordering rule {rule_id} in "
                        f"{ruleset_name}: {type(error).__name__}: {error}")
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

    def _current_owned_order(self, ruleset_name, desired_ids):
        """
        The order Checkmk currently lists this run's own rules in, or
        None when it cannot be reconstructed.

        Built from the snapshot ``clean_rules`` captured plus the rules
        created afterwards (Checkmk appends those at the bottom, in the
        order they were sent). Returning None makes the caller fall back
        to reordering everything, which is always correct — just slower.
        """
        captured = self._cmk_order_by_ruleset.get(ruleset_name)
        if captured is None:
            return None
        desired_set = set(desired_ids)
        order = [rid for rid in captured if rid in desired_set]
        for rule_id in self._created_order_by_ruleset.get(ruleset_name, []):
            if rule_id in desired_set and rule_id not in order:
                order.append(rule_id)
        if set(order) != desired_set or len(order) != len(desired_ids):
            # Some rule cannot be placed — do not guess, move everything.
            return None
        return order

    @staticmethod
    def _moves_needed(desired_ids, current_order):
        """
        The indices in ``desired_ids`` that actually have to be moved.

        Walking the desired order and only moving a rule when it does
        not already sit right behind its predecessor turns "reorder
        everything" into "reorder what is out of place" — an untouched
        ruleset needs no request at all, a single displaced rule needs
        one instead of N-1. The simulated list mirrors what Checkmk
        does, so later comparisons see the earlier moves.
        """
        simulated = list(current_order)
        moves = []
        for index in range(1, len(desired_ids)):
            rule_id = desired_ids[index]
            previous = desired_ids[index - 1]
            if simulated.index(rule_id) == simulated.index(previous) + 1:
                continue
            moves.append(index)
            simulated.remove(rule_id)
            simulated.insert(simulated.index(previous) + 1, rule_id)
        return moves

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
        with make_progress() as progress:

            total_rules = sum(len(r) for r in self.rulsets_by_type.values())
            task1 = progress.add_task(
                f"Create across {len(self.rulsets_by_type)} rulesets ({total_rules} rules)",
                total=len(self.rulsets_by_type),
            )
            for ruleset_name, rules in self.rulsets_by_type.items():
                if ruleset_name in self._failed_rulesets:
                    # Cleanup could not read this ruleset, so no rule in it
                    # carries a _skip_create marker — creating now would
                    # duplicate every rule that already exists there.
                    progress.advance(task1)
                    continue
                for rule in rules:
                    template = {
                        "ruleset": f"{ruleset_name}",
                        "folder": rule['folder'],
                        "properties": {
                            "disabled": False,
                            "description": rule.get('description')
                                           or self.rule_marker,
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
                        if rule.get('_cmk_id'):
                            self._created_order_by_ruleset.setdefault(
                                ruleset_name, []).append(rule['_cmk_id'])
                        self.log_details.append(("INFO",
                                              f"Created Rule in {ruleset_name}: {rule['value']}"))
                    except CmkException as error:
                        # log_error prints the reason on the CLI; the full
                        # request template only goes into the log detail to
                        # keep the terminal output readable.
                        self.log_error(
                            f"Could not create Rule in {ruleset_name}: {error}")
                        self.log_details.append(
                            ("ERROR_DETAIL", f"Failed template: {template}"))
                progress.advance(task1)


    @staticmethod
    def _compare_rule(rule, cmk):
        """
        Compare one locally generated rule against a Checkmk rule and
        report every criterion on its own. ``cmk`` carries the Checkmk
        side as ``condition`` / ``comment`` / ``value`` / ``folder``.
        Returns None when either value literal cannot be parsed.
        """
        try:
            local_value = ast.literal_eval(rule['value'])
            remote_value = ast.literal_eval(cmk['value'])
        except (SyntaxError, KeyError):
            return None
        value_match = deep_compare(local_value, remote_value,
                                   strict=bool(rule.get('enforce_value')))
        condition_match = rule['condition'] == cmk['condition']
        return {
            'local_value': local_value,
            'remote_value': remote_value,
            'condition': condition_match,
            # Same condition apart from the coalesced host list — the one
            # part that changes whenever a host enters or leaves the
            # outcome. Such a rule is adjusted, not replaced.
            'hosts_only': not condition_match and
                          condition_without_hosts(rule['condition']) ==
                          condition_without_hosts(cmk['condition']),
            'comment': rule.get('comment', '') == cmk['comment'],
            'value': value_match,
            # ``keep_value`` outcomes are written once and then left for the
            # operator to adjust in Checkmk, so drift is not a mismatch.
            'value_ok': value_match or bool(rule.get('keep_value')),
            'folder': cmk['folder'].lower() ==
                      normalize_cmk_folder(rule['folder']).lower(),
        }

    def _sync_description(self, cmk_rule, rule, ruleset_name):
        """
        Rewrite the description of a Checkmk rule that matches ours in every
        other respect but carries an outdated one - a renamed Setup Rule, or
        a rule created before the description named its source.

        Everything else is sent back exactly as Checkmk has it: a
        ``keep_value`` rule must keep the value the operator adjusted.
        """
        wanted = rule.get('description') or self.rule_marker
        properties = dict(cmk_rule['extensions']['properties'])
        if properties.get('description', '') == wanted:
            return
        properties['description'] = wanted
        rule_id = cmk_rule['id']
        payload = {
            "properties": properties,
            "conditions": cmk_rule['extensions']['conditions'],
            "value_raw": cmk_rule['extensions']['value_raw'],
        }
        try:
            self.update_rule(rule_id, payload)
            print(f"{CC.OKBLUE} *{CC.ENDC} UPDATE description of Rule in "
                  f"{ruleset_name} {rule_id}")
            self.log_details.append((
                "INFO",
                f"Updated description of Rule in {ruleset_name} {rule_id}: "
                f"{wanted}",
            ))
        except CmkException as error:
            self.log_error(
                f"Could not update description of Rule {rule_id} in "
                f"{ruleset_name}: {error}")

    def _explain_deletion(self, rules, cmk):
        """
        Say why none of the locally generated rules paired with the
        Checkmk rule that is about to be deleted.

        A run that suddenly wants to delete hundreds of its own rules is
        almost always one changed criterion — a reworked condition, a
        renamed folder, a dropped comment — not hundreds of unrelated
        events. Returns ``(reason, detail)``: the short reason groups the
        deletions in the summary, the detail is the concrete diff.
        """
        if not rules:
            return ('no rule generated for this ruleset any more',
                    'The run no longer generates any rule for this ruleset, '
                    'so every rule the Syncer owns in it is removed.')
        best_score = -1
        best_rule = None
        best_comparison = None
        for rule in rules:
            comparison = self._compare_rule(rule, cmk)
            if comparison is None:
                continue
            score = sum((comparison['condition'], comparison['comment'],
                         comparison['value_ok'], comparison['folder']))
            if score > best_score:
                best_score, best_rule, best_comparison = \
                    score, rule, comparison
        if best_comparison is None:
            return ('value not parsable',
                    f'No generated rule could be compared: {cmk["value"]}')
        if best_comparison['hosts_only']:
            cmk_hosts = condition_hosts(cmk['condition'])
            local_hosts = condition_hosts(best_rule['condition'])
            added = [host for host in local_hosts if host not in cmk_hosts]
            removed = [host for host in cmk_hosts if host not in local_hosts]
            return ('host list changed',
                    f'The rule covers {len(cmk_hosts)} host(s) in Checkmk '
                    f'and {len(local_hosts)} now; added: {added or "-"}, '
                    f'removed: {removed or "-"}. It could not be adjusted '
                    'in place because more than one generated rule fits.')
        if not best_comparison['condition']:
            return ('condition no longer generated',
                    'No generated rule carries this condition. Checkmk: '
                    f'{pformat(cmk["condition"])} — closest generated rule: '
                    f'{pformat(best_rule["condition"])}')
        mismatches = []
        if not best_comparison['comment']:
            mismatches.append(
                f'comment: Checkmk {cmk["comment"]!r} != '
                f'generated {best_rule.get("comment", "")!r}')
        if not best_comparison['folder']:
            mismatches.append(
                f'folder: Checkmk {cmk["folder"]} != generated '
                f'{normalize_cmk_folder(best_rule["folder"])}')
        if not best_comparison['value_ok']:
            mismatches.append('value: ' + analyze_value_differences(
                best_comparison['local_value'],
                best_comparison['remote_value']))
        if not mismatches:
            # Every criterion lines up, so the generated rule does exist —
            # it was just already paired with another Checkmk rule.
            return ('duplicate in Checkmk',
                    'An identical rule exists more than once in Checkmk; '
                    'the generated rule paired with the other copy.')
        reason = ' and '.join(part.split(':', 1)[0] for part in mismatches)
        return (f'{reason} changed', '; '.join(mismatches))

    # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    def clean_rules(self):
        """
        Clean not longer needed Rules from Checkmk
        """
        print(f"{CC.OKGREEN} -- {CC.ENDC} Clean existing CMK configuration")
        with make_progress() as progress:

            total_rules = sum(len(r) for r in self.rulsets_by_type.values())
            task1 = progress.add_task(
                f"Cleanup across {len(self.rulsets_by_type)} rulesets ({total_rules} rules)",
                total=len(self.rulsets_by_type),
            )
            delete_reasons = {}
            for ruleset_name, rules in self.rulsets_by_type.items():
                url = f"domain-types/rule/collections/all?ruleset_name={ruleset_name}"
                try:
                    rule_response = self.request(url, method="GET")[0]
                except CmkException as error:
                    # A timeout or error here means we do not know what is
                    # in this ruleset. Leave it alone for this run — the
                    # other rulesets are still exported, and the next run
                    # picks this one up again.
                    self._failed_rulesets.add(ruleset_name)
                    self.log_error(
                        f"Skipped ruleset {ruleset_name}, could not read "
                        f"its current rules: {error}")
                    progress.advance(task1)
                    continue
                # Capture the order of syncer-owned rule IDs as CMK
                # currently lists them. sort_rules uses this snapshot to
                # skip the move chain when the desired order already
                # matches reality.
                self._cmk_order_by_ruleset[ruleset_name] = [
                    cmk_rule['id'] for cmk_rule in rule_response['value']
                    if self._owns_rule(cmk_rule)
                ]
                for cmk_rule in rule_response['value']:
                    if not self._owns_rule(cmk_rule):
                        continue



                    value = cmk_rule['extensions']['value_raw']
                    cmk_condition = cmk_rule['extensions']['conditions']
                    # Folder the rule currently lives in on the Checkmk side.
                    # Compared against the outcome's configured folder so a rule
                    # that drifted into the wrong folder is corrected instead of
                    # silently accepted.
                    cmk_folder = normalize_cmk_folder(
                        cmk_rule['extensions'].get('folder', '/'))
                    rule_found = False
                    condition_matches = []  # Collect all rules with matching conditions
                    # Rules that differ from the Checkmk one only in the
                    # coalesced host list (see optimize_rules).
                    host_list_matches = []

                    cmk_comment = cmk_rule['extensions']['properties'].get(
                        'comment', '')
                    cmk_facts = {
                        'condition': cmk_condition,
                        'comment': cmk_comment,
                        'value': value,
                        'folder': cmk_folder,
                    }
                    for rule in list(rules):
                        # ``sort_rules`` needs every owned rule to keep
                        # its (rulesets_by_type) slot with a captured
                        # ``_cmk_id``. Skip entries already paired with
                        # a different cmk_rule on a previous iteration
                        # of this outer loop — re-matching them would
                        # only produce duplicates.
                        if rule.get('_skip_create'):
                            continue
                        # Comment is admin-supplied free text per outcome
                        # (RuleMngmtOutcome.comment). When several
                        # outcomes share the same condition+value the
                        # comment is the only distinguishing identifier
                        # — without it ``sort_rules`` ends up pairing
                        # local→cmk in CMK iteration order, silently
                        # cancelling the configured folder_index
                        # ordering on idempotent re-runs. The folder is
                        # part of the identity too: a rule that drifted
                        # into another folder has to be recreated in the
                        # configured one.
                        comparison = self._compare_rule(rule, cmk_facts)
                        if comparison is None:
                            logger.debug("Invalid Value: '%s' or '%s'", rule['value'], value)
                            continue
                        condition_match = comparison['condition']
                        comment_match = comparison['comment']
                        value_match = comparison['value']
                        folder_match = comparison['folder']
                        value_ok = comparison['value_ok']

                        # A rule whose condition differs only in the
                        # coalesced host list, but which is otherwise the
                        # very same rule, is a candidate for adjusting the
                        # host list in place.
                        if comparison['hosts_only'] and comment_match \
                                and folder_match and value_ok:
                            host_list_matches.append(rule)

                        # Collect all rules with matching conditions
                        if condition_match:
                            condition_matches.append({
                                'rule': rule,
                                'expected_value': comparison['local_value'],
                                'actual_value': comparison['remote_value'],
                                'value_match': value_match,
                                'folder_match': folder_match,
                            })

                        if condition_match and comment_match and value_ok \
                                and folder_match:
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
                            self._sync_description(cmk_rule, rule, ruleset_name)
                            break

                    # If exactly one of our rules has the same condition but a
                    # different value, this is not a stale rule — it's a value
                    # drift we should push to Checkmk in place. Updating via
                    # PUT preserves the rule id and audit history and avoids a
                    # destructive delete+recreate (which briefly removes the
                    # rule from the active policy and churns ids).
                    if not rule_found and len(condition_matches) == 1 and \
                            condition_matches[0]['folder_match'] and \
                            not condition_matches[0]['rule'].get('keep_value') and \
                            not condition_matches[0]['value_match']:
                        our_rule = condition_matches[0]['rule']
                        rule_id = cmk_rule['id']
                        update_payload = {
                            "properties": {
                                "disabled": False,
                                "description": our_rule.get('description')
                                               or self.rule_marker,
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
                            self.log_error(
                                f"Could not update Rule {rule_id} in "
                                f"{ruleset_name}: {error}")

                    # A host entering or leaving a coalesced rule changed
                    # its condition, which used to read as "this rule is
                    # gone" and cost a delete plus a recreate of a rule
                    # covering hundreds of hosts. Adjust the host list in
                    # place instead — same rule, same id, same history.
                    # Only when exactly one generated rule fits: with
                    # several candidates we cannot tell which one the
                    # Checkmk rule grew out of.
                    if not rule_found and not condition_matches and \
                            len(host_list_matches) == 1:
                        our_rule = host_list_matches[0]
                        rule_id = cmk_rule['id']
                        cmk_hosts = condition_hosts(cmk_condition)
                        our_hosts = condition_hosts(our_rule['condition'])
                        update_payload = {
                            "properties": {
                                "disabled": False,
                                "description": our_rule.get('description')
                                               or self.rule_marker,
                                "comment": our_rule['comment'],
                            },
                            "conditions": our_rule['condition'],
                            "value_raw": our_rule['value'],
                        }
                        try:
                            self.update_rule(rule_id, update_payload)
                            print(f"{CC.OKBLUE} *{CC.ENDC} UPDATE host list of "
                                  f"Rule in {ruleset_name} {rule_id} "
                                  f"({len(cmk_hosts)} -> {len(our_hosts)} hosts)")
                            our_rule['_cmk_id'] = rule_id
                            our_rule['_skip_create'] = True
                            rule_found = True
                            self.log_details.append((
                                "INFO",
                                f"Updated host list of Rule in {ruleset_name} "
                                f"{rule_id}: {len(cmk_hosts)} -> "
                                f"{len(our_hosts)} hosts",
                            ))
                        except CmkException as error:
                            self.log_error(
                                f"Could not update host list of Rule {rule_id} "
                                f"in {ruleset_name}: {error}")

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
                        # Why this rule is going: without it a run that
                        # deletes hundreds of its own rules gives the
                        # operator nothing to act on.
                        reason, reason_detail = self._explain_deletion(
                            rules, cmk_facts)
                        delete_reasons[reason] = \
                            delete_reasons.get(reason, 0) + 1
                        print(f"{CC.OKBLUE} *{CC.ENDC} DELETE Rule in "
                              f"{ruleset_name} {rule_id} ({reason})")
                        if self.debug:
                            print(f"{CC.OKCYAN}   {reason_detail}{CC.ENDC}")
                        self.log_details.append((
                            "INFO",
                            f"Delete reason for {rule_id} in {ruleset_name} "
                            f"({reason}): {reason_detail}"))

                        # Show details only for potentially problematic cases
                        if deletion_details:
                            print(f"{CC.WARNING}   {deletion_details}{CC.ENDC}")

                        url = f'/objects/rule/{rule_id}'
                        try:
                            self.request(url, method="DELETE")
                        except CmkException as error:
                            self.log_error(
                                f"Could not delete Rule {rule_id} in "
                                f"{ruleset_name}: {error}")
                            continue

                        # Log with details if it's a potential flapping rule
                        log_entry = f"Deleted Rule in {ruleset_name} {rule_id}"
                        if deletion_details:
                            log_entry += f" - {deletion_details}"
                        self.log_details.append(("INFO", log_entry))
                progress.advance(task1)
        self._report_delete_reasons(delete_reasons)

    def _report_delete_reasons(self, delete_reasons):
        """
        Summarise why the run deleted rules. Hundreds of deletions almost
        always share one cause, and that cause is what has to be fixed —
        the per-rule lines scroll past, this line does not.
        """
        if not delete_reasons:
            return
        total = sum(delete_reasons.values())
        summary = ", ".join(
            f"{count}x {reason}" for reason, count
            in sorted(delete_reasons.items(), key=lambda x: -x[1]))
        message = f"Removing {total} rule(s) — reasons: {summary}"
        print(f"{CC.WARNING}  ** {CC.ENDC}{message}")
        if not self.debug:
            print(f"{CC.OKCYAN}  ** {CC.ENDC}Run with --debug to see the "
                  f"difference behind each deletion")
        self.log_details.append(("INFO", message))

    def clean_orphaned_rules(self):
        """
        Remove syncer-owned rules from rulesets the run no longer touches.

        ``clean_rules`` only visits rulesets present in ``rulsets_by_type`` —
        the ones the current run still generates rules for. When the last rule
        targeting a ruleset is disabled or deleted, that ruleset drops out of
        ``rulsets_by_type`` entirely, so its previously created (marker-owned)
        rules would linger in Checkmk forever. Opt-in via the account's
        ``remove_orphaned_rules`` setting: scan every used ruleset the run no
        longer touches and delete the rules carrying this run's marker.

        ``keep_value`` rules are deleted here like any other — once a rule is
        no longer generated there is nothing left to keep.
        """
        if not self.config.get('remove_orphaned_rules'):
            return
        print(f"{CC.OKGREEN} -- {CC.ENDC} Remove orphaned syncer rules")
        try:
            orphan_rulesets = [
                name for name in self.list_used_rulesets()
                if name not in self.rulsets_by_type
            ]
        except CmkException as error:
            self.log_error(f"Could not list used rulesets: {error}")
            return
        for ruleset_name in orphan_rulesets:
            url = f"domain-types/rule/collections/all?ruleset_name={ruleset_name}"
            try:
                rule_response = self.request(url, method="GET")[0]
            except CmkException as error:
                self.log_error(
                    f"Skipped orphan check for {ruleset_name}: {error}")
                continue
            for cmk_rule in rule_response['value']:
                if not self._owns_rule(cmk_rule):
                    continue
                rule_id = cmk_rule['id']
                print(f"{CC.OKBLUE} *{CC.ENDC} DELETE orphaned Rule in "
                      f"{ruleset_name} {rule_id}")
                try:
                    self.request(f'/objects/rule/{rule_id}', method="DELETE")
                except CmkException as error:
                    self.log_error(
                        f"Could not delete orphaned Rule {rule_id} in "
                        f"{ruleset_name}: {error}")
                    continue
                self.log_details.append((
                    "INFO",
                    f"Deleted orphaned Rule in {ruleset_name} {rule_id}"))
