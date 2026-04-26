"""
Rule Import/ Export

Two layers of API:

* ``iter_rules_of_type``, ``iter_all_rules``, ``import_one_rule``,
  ``import_rule_lines`` — pure helpers that don't print and don't
  touch the filesystem. Reusable by the CLI, the REST API, and the
  autorules path.
* ``export_rules``, ``export_all_rules``, ``import_rules`` — CLI
  wrappers that print progress and read/write files.
"""
import json
from json.decoder import JSONDecodeError
import importlib
from datetime import datetime

from mongoengine.errors import NotUniqueError, ValidationError
from .rule_definitions import rules as enabled_rules


HOST_COLLECTION_RULE_TYPE = 'host_objects'
ACCOUNTS_RULE_TYPE = 'accounts'
USERS_RULE_TYPE = 'users'


def get_ruletype_by_filename(filename):
    """
    Try to guess the rule_type using the filename
    """
    model_name = filename.split('/')[-1].split('_')[0]
    for rule_type, model_data in enabled_rules.items():
        if model_data[1] == model_name:
            return rule_type
    return False


def _model_class_for(rule_type):
    """Resolve the model class for *rule_type* or None on unknown type."""
    if rule_type not in enabled_rules:
        return None
    module_path, class_name = enabled_rules[rule_type]
    module = importlib.import_module(module_path)
    return getattr(module, class_name, None)


def iter_rules_of_type(rule_type):
    """Yield JSON strings (one per rule) for *rule_type*. Empty when unknown."""
    model_class = _model_class_for(rule_type)
    if model_class is None:
        return
    for db_rule in model_class.objects():
        yield db_rule.to_json()


# Backwards-compat alias — older callers used this name.
export_rules_from_model = iter_rules_of_type


def iter_all_rules(include_hosts=False, include_accounts=False, include_users=False):
    """Yield ``(rule_type, json_string)`` for every enabled rule type, in
    sorted ``rule_type`` order.

    Hosts/objects, accounts, and users are skipped by default since they
    are usually not what you want in a rule backup. Pass the matching
    ``include_*=True`` flag to opt in. User exports contain hashed
    passwords and role assignments — treat the resulting data as secret.
    """
    skip = {
        HOST_COLLECTION_RULE_TYPE: not include_hosts,
        ACCOUNTS_RULE_TYPE: not include_accounts,
        USERS_RULE_TYPE: not include_users,
    }
    for rule_type in sorted(enabled_rules):
        if skip.get(rule_type):
            continue
        for rule in iter_rules_of_type(rule_type):
            yield rule_type, rule


def _save_rule(json_dict, model_class):
    """Persist a rule from a parsed JSON dict.

    Returns one of ``'imported'``, ``'duplicate'``, ``'invalid'``.
    """
    db_ref = model_class()
    new = db_ref.from_json(json.dumps(json_dict))
    try:
        new.save(force_insert=True)
    except NotUniqueError:
        return 'duplicate'
    except ValidationError:
        return 'invalid'
    return 'imported'


def import_one_rule(json_dict, rule_type):
    """Import a single rule dict for *rule_type*. No printing.

    Returns ``'imported'``, ``'duplicate'``, ``'invalid'``, or
    ``'unknown_type'``.
    """
    model_class = _model_class_for(rule_type)
    if model_class is None:
        return 'unknown_type'
    return _save_rule(json_dict, model_class)


def import_rule_lines(lines, default_rule_type=None):
    """Consume an iterable of text lines (or already-parsed dicts) and
    import them. Mirrors the on-disk format: ``{"rule_type": "..."}``
    header lines switch the active rule type for the lines that follow.

    Returns ``{rule_type: imported_count}``.
    """
    rule_type = default_rule_type
    model_class = _model_class_for(rule_type) if rule_type else None
    counts = {}
    for line in lines:
        if isinstance(line, str):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                json_dict = json.loads(stripped)
            except JSONDecodeError:
                continue
        else:
            json_dict = line
        if (isinstance(json_dict, dict)
                and len(json_dict) == 1 and 'rule_type' in json_dict):
            rule_type = json_dict['rule_type']
            model_class = _model_class_for(rule_type)
            continue
        if model_class is None:
            continue
        status = _save_rule(json_dict, model_class)
        if status == 'imported':
            counts[rule_type] = counts.get(rule_type, 0) + 1
    return counts


def grouped_rules_export(include_hosts=False, include_accounts=False,
                         include_users=False):
    """Return ``{exported_at, rules: {rule_type: [dict, ...]}}`` for every
    enabled rule type. Used by both the REST ``/rules/export`` endpoint
    and the MCP ``export_all_rules`` tool."""
    grouped = {}
    for rule_type, raw in iter_all_rules(
        include_hosts=include_hosts,
        include_accounts=include_accounts,
        include_users=include_users,
    ):
        try:
            grouped.setdefault(rule_type, []).append(json.loads(raw))
        except (ValueError, TypeError):
            continue
    return {
        'exported_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'rules': grouped,
    }


def import_json_bundle(payload):
    """Import a structured JSON payload that mirrors the export shape.

    Accepts:

    * ``{"rule_type": "...", "rules": [<dict>, ...]}`` — single-type
    * ``{"rules": {"<rule_type>": [<dict>, ...], ...}}`` — multi-type,
      same shape ``GET /rules/export`` returns

    Returns ``{rule_type: imported_count}``. Unknown shapes return ``{}``.
    """
    if not isinstance(payload, dict):
        return {}
    rules_field = payload.get('rules')
    if isinstance(rules_field, list):
        return import_rule_lines(rules_field,
                                 default_rule_type=payload.get('rule_type'))
    if isinstance(rules_field, dict):
        counts = {}
        for rule_type, items in rules_field.items():
            if not isinstance(items, list):
                continue
            for k, v in import_rule_lines(items, default_rule_type=rule_type).items():
                counts[k] = counts.get(k, 0) + v
        return counts
    return {}


# ---------------------------------------------------------------------------
# CLI wrappers — print progress, read/write files
# ---------------------------------------------------------------------------


def export_rules(rule_type):
    """Export rules of one type, printed line-by-line (CLI)."""
    if rule_type.lower() in enabled_rules:
        print(json.dumps({"rule_type": rule_type}))
        for rule in iter_rules_of_type(rule_type):
            print(rule)
    else:
        print("Ruletype not supported")
        print("Currently supported:")
        print()
        for rulename in sorted(enabled_rules):
            print(rulename)


def export_all_rules(target_path=None, include_hosts=False,
                     include_accounts=False, include_users=False):
    """
    Export all Rules of every known type into a single file (CLI).
    """
    if not target_path:
        target_path = f"syncer_rules_export_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    skipped = []
    if not include_hosts:
        skipped.append(f"--include-hosts to export {HOST_COLLECTION_RULE_TYPE}")
    if not include_accounts:
        skipped.append(f"--include-accounts to export {ACCOUNTS_RULE_TYPE}")
    if not include_users:
        skipped.append(f"--include-users to export {USERS_RULE_TYPE}")
    for hint in skipped:
        print(f"* Skipped (use {hint})")

    total = 0
    last_type = None
    with open(target_path, 'w', encoding='utf-8') as outfile:
        for rule_type, rule in iter_all_rules(include_hosts, include_accounts, include_users):
            if rule_type != last_type:
                outfile.write(json.dumps({"rule_type": rule_type}) + "\n")
                last_type = rule_type
                print(f"* Exporting {rule_type}")
            outfile.write(rule + "\n")
            total += 1
    print(f"Wrote {total} rules to {target_path}")


def import_line(json_dict, model, rule_type):
    """CLI helper: import a single line and print progress."""
    print(f"* Import {json_dict['_id']}")
    status = _save_rule(json_dict, getattr(model, enabled_rules[rule_type][1]))
    if status == 'duplicate':
        print("   Already existed")
    elif status == 'invalid':
        print(f"Problem with entry: {json_dict}")


def import_rules(rulefile_path):
    """
    Import Rules into the CMDB Syncer (CLI).
    Supports single-type files (rule_type guessed from filename) and
    multi-type files with multiple ``{"rule_type": "..."}`` header lines.
    """
    with open(rulefile_path, encoding='utf-8') as rulefile:
        text = rulefile.read()

    has_header = any(
        line.strip().startswith('{"rule_type"') and 'rule_type' in line
        for line in text.splitlines()
    )

    default_type = None
    if not has_header:
        default_type = get_ruletype_by_filename(rulefile_path)
        if default_type not in enabled_rules:
            print("Ruletype not supported")
            print(f"Currently supported: {', '.join(enabled_rules.keys())}")
            return

    counts = import_rule_lines(text.splitlines(), default_rule_type=default_type)
    for rule_type, count in counts.items():
        print(f"== {rule_type}: imported {count} ==")
