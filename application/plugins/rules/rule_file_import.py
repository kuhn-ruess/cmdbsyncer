"""
Import of a rules file from the page of one rule type

Unlike the command line this import checks the whole file first and writes
nothing when one record is bad, and it refuses a file of another rule type.
Writing goes through the same ``_save_rule`` as every other rule import.

A file can come from a path in a browser form, so whatever is told about a
file read from disk stays free of its content: with ``detail`` off the
messages name positions and fields of the model, no values.
"""
import json
import os
import stat
from json.decoder import JSONDecodeError

from mongoengine.errors import ValidationError
from mongoengine.fields import EmbeddedDocumentField, ListField, MapField

from application.helpers.syncer_jinja import check_jinja_syntax

from .rule_definitions import rules as enabled_rules
from .rule_import_export import (
    _model_class_for,
    _save_rule,
    conflict_filters,
    get_ruletype_by_filename,
)

MAX_FILE_BYTES = 5 * 1024 * 1024
FILE_SUFFIXES = ('.syncer_json', '.jsonl', '.json')

# Fields which hold no templates, whatever text is in them.
_NOT_JINJA_FIELDS = {'_id', 'name', 'documentation'}


class RuleImportError(Exception):
    """The file can't be used at all. The message is safe to show."""


def read_rule_file(path, root):
    """
    The text of the rule file *path*, which must be below the folder *root*.

    A relative path starts at *root*. Only regular files with a known suffix
    and limited size are read, and no part of the path below *root* may be a
    symbolic link: whoever can place a link there would decide what the
    server reads.
    """
    real_root = os.path.realpath(root)
    outside = RuleImportError("The path must lead to a file in the Files folder")
    if '\0' in path:
        raise outside
    wanted = os.path.normpath(os.path.join(real_root, path))
    for base in (os.path.abspath(root), real_root):
        if wanted.startswith(base + os.sep):
            full_path = os.path.join(real_root, os.path.relpath(wanted, base))
            break
    else:
        raise outside
    if not full_path.endswith(FILE_SUFFIXES):
        raise RuleImportError(
            f"Only files ending in {', '.join(FILE_SUFFIXES)} can be imported")
    if os.path.realpath(full_path) != full_path:
        raise RuleImportError("The path contains a symbolic link")
    try:
        handle = os.open(full_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise RuleImportError("The file can't be read") from error
    try:
        if not stat.S_ISREG(os.fstat(handle).st_mode):
            raise RuleImportError("The path is not a regular file")
        with open(handle, 'rb', closefd=False) as rule_file:
            content = rule_file.read(MAX_FILE_BYTES + 1)
    except OSError as error:
        raise RuleImportError("The file can't be read") from error
    finally:
        os.close(handle)
    if len(content) > MAX_FILE_BYTES:
        raise RuleImportError(
            f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    try:
        return content.decode('utf-8')
    except UnicodeDecodeError as error:
        raise RuleImportError("The file is not UTF-8 text") from error


def _is_header(record):
    """True for a ``{"rule_type": "..."}`` line in front of its rules."""
    return isinstance(record, dict) and len(record) == 1 \
        and isinstance(record.get('rule_type'), str)


def _parse_items(items, label):
    """``(records, declared types)`` of a list of parsed entries."""
    records = []
    declared = set()
    for number, item in enumerate(items, 1):
        if _is_header(item):
            declared.add(item['rule_type'])
        else:
            records.append((f"{label} {number}", item))
    return records, declared


def _parse_document(document):
    """``(records, declared types)`` of a text that is one JSON document."""
    if isinstance(document, list):
        return _parse_items(document, 'Record')
    if not isinstance(document, dict):
        return [('Record 1', document)], set()
    rules_field = document.get('rules')
    if isinstance(rules_field, list):
        records, declared = _parse_items(rules_field, 'Record')
        if isinstance(document.get('rule_type'), str):
            declared.add(document['rule_type'])
        return records, declared
    if isinstance(rules_field, dict):
        records = []
        declared = set(rules_field)
        for rule_type, items in rules_field.items():
            if isinstance(items, list):
                records += _parse_items(items, f"{rule_type}, record")[0]
        return records, declared
    if _is_header(document):
        return [], {document['rule_type']}
    return [('Record 1', document)], set()


def parse_rule_text(text):
    """
    Read every form a rule export comes in: lines of JSON with or without
    ``{"rule_type": ...}`` lines, a JSON list, one rule, or the bundle of the
    REST API.

    Returns ``(records, declared types, errors)`` with ``records`` as a list
    of ``(position, parsed record)``.
    """
    text = text.lstrip('﻿').strip()
    if not text:
        return [], set(), ["There is nothing to import"]
    try:
        records, declared = _parse_document(json.loads(text))
        return records, declared, []
    except RecursionError:
        return [], set(), ["The JSON is nested too deeply"]
    except JSONDecodeError as error:
        whole_error = error

    records = []
    declared = set()
    errors = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except RecursionError:
            errors.append(f"Line {number}: the JSON is nested too deeply")
        except JSONDecodeError as error:
            errors.append(f"Line {number}: not valid JSON, {error.msg} "
                          f"at column {error.colno}")
        else:
            if _is_header(record):
                declared.add(record['rule_type'])
            else:
                records.append((f"Line {number}", record))
    if errors and not records and not declared:
        # Not lines of JSON at all: a broken document spanning several lines.
        return [], set(), [f"Not valid JSON, {whole_error.msg} at line "
                           f"{whole_error.lineno}, column {whole_error.colno}"]
    return records, declared, errors


def _type_of_file_name(source_name):
    """The rule type a file name stands for: the name of the export of the
    page or of Rules in Git. None if it says nothing."""
    if not source_name:
        return None
    basename = os.path.basename(source_name)
    stem = os.path.splitext(basename)[0]
    return stem if stem in enabled_rules else get_ruletype_by_filename(basename) or None


def _type_error(declared, rule_type, source_name):
    """Why the file does not belong to *rule_type*, None if nothing speaks
    against it."""
    others = sorted(x for x in declared if x != rule_type)
    if others:
        # A name which is no rule type could be any content of the file.
        names = ', '.join(x for x in others if x in enabled_rules) or 'an unknown type'
        return (f"This file holds rules of {names}. This page only imports "
                f"{rule_type}: use the page of that rule type.")
    from_name = None if declared else _type_of_file_name(source_name)
    if from_name and from_name != rule_type:
        return (f"The file name belongs to rules of {from_name}. This page only "
                f"imports {rule_type}: use the page of that rule type.")
    return None


def _nested_document(field):
    """The embedded document class below *field*, None if there is none."""
    while isinstance(field, (ListField, MapField)):
        field = field.field
    if isinstance(field, EmbeddedDocumentField):
        return field.document_type
    return None


def _unknown_fields(raw, document, prefix=''):
    """
    The keys of *raw* the rule type does not have. The models are not strict,
    so loading a rule of another type would drop these without a word.
    """
    # pylint: disable=protected-access
    fields = {field.db_field: field for field in document._fields.values()}
    unknown = []
    for key, value in raw.items():
        if key == '_cls':
            continue
        if key not in fields:
            unknown.append(f"{prefix}{key}")
            continue
        nested = _nested_document(fields[key])
        if nested is None:
            continue
        entries = value if isinstance(value, list) else [value]
        for index, entry in enumerate(entries):
            if isinstance(entry, dict):
                position = f"{index}." if isinstance(value, list) else ''
                unknown += _unknown_fields(entry, nested, f"{prefix}{key}.{position}")
    return unknown


def _flat_errors(errors, prefix=''):
    """Turn the tree of a ``ValidationError`` into ``[(field, message)]``."""
    if not isinstance(errors, dict):
        return [(prefix.rstrip('.'), str(errors))]
    flat = []
    for key, value in errors.items():
        flat += _flat_errors(value, f"{prefix}{key}.")
    return flat


def _jinja_warnings(value, detail, path=''):
    """Fields of a record whose template does not compile. They are refused
    only where the form of that rule type refuses them too, so a rule from
    an export keeps importing."""
    if isinstance(value, dict):
        items = [(key, item) for key, item in value.items()
                 if path or key not in _NOT_JINJA_FIELDS]
    elif isinstance(value, list):
        items = list(enumerate(value))
    else:
        items = []
    warnings = []
    for key, item in items:
        warnings += _jinja_warnings(item, detail, f"{path}{key}.")
    if isinstance(value, str) and (defect := check_jinja_syntax(value)):
        reason = f": {defect}" if detail else ''
        warnings.append(f"{path.rstrip('.')}: the Jinja does not compile{reason}")
    return warnings


def _display_name(raw, model_class):
    """What a record is called on the page."""
    # pylint: disable=protected-access
    candidates = ['name'] + [field.db_field for field in model_class._fields.values()
                             if getattr(field, 'unique', False)]
    for key in candidates:
        if isinstance(raw.get(key), str) and raw[key]:
            return raw[key]
    doc_id = raw.get('_id')
    if isinstance(doc_id, dict):
        doc_id = doc_id.get('$oid')
    return str(doc_id) if doc_id else '(no name)'


def _existing_rules(raw, model_class):
    """Names of the stored rules the record collides with."""
    found = {}
    for conflict in conflict_filters(raw, model_class, match_name=True):
        try:
            for doc in model_class.objects(**conflict):
                found[str(doc.pk)] = _display_name(json.loads(doc.to_json()), model_class)
        except (ValidationError, TypeError):
            continue
    return sorted(found.values())


def _load_problems(raw, model_class, detail):
    """``(document, [])`` of a record, or ``(None, problems)`` if it does not
    load and validate as *model_class*."""
    try:
        doc = model_class().from_json(json.dumps(raw))
        doc.validate()
    except ValidationError as error:
        problems = _flat_errors(error.to_dict() or {'': error.message})
        if detail:
            return None, [f"{field}: {message}" if field else message
                          for field, message in problems]
        return None, [f"Invalid value in {field}" if field else "Invalid value"
                      for field, _message in problems]
    except Exception as error:  # pylint: disable=broad-exception-caught
        # from_json raises whatever the field and bson conversions run into
        return None, [f"Not a valid rule: {error}" if detail
                      else "Not a valid rule of this type"]
    return doc, []


def _check_record(raw, model_class, detail, check):
    """The problems of one record which keep it from being imported."""
    if not isinstance(raw, dict):
        return ["This is not a JSON object"]
    unknown = _unknown_fields(raw, model_class)
    if unknown:
        return [f"Unknown field(s) for this rule type: {', '.join(unknown)}" if detail
                else f"{len(unknown)} unknown field(s) for this rule type"]
    doc, problems = _load_problems(raw, model_class, detail)
    if problems or not check:
        return problems
    return list(check(doc))


def _duplicate_in_file(raw, model_class, seen, where):
    """Which earlier record of the file holds the same id or name."""
    found = None
    for conflict in conflict_filters(raw, model_class, match_name=True):
        key = json.dumps(conflict, sort_keys=True, default=str)
        found = found or seen.get(key)
        seen.setdefault(key, where)
    return found


def _check_rows(records, model_class, detail, check):
    """One row per record for the page, see ``plan_import``."""
    rows = []
    seen = {}
    for where, raw in records:
        row = {'where': where, 'raw': raw, 'errors': [], 'warnings': [],
               'existing': [], 'name': '', 'enabled': None}
        rows.append(row)
        row['errors'] = _check_record(raw, model_class, detail, check)
        if isinstance(raw, dict) and not row['errors']:
            row['name'] = _display_name(raw, model_class)
            row['enabled'] = raw.get('enabled')
            row['warnings'] = _jinja_warnings(raw, detail)
            row['existing'] = _existing_rules(raw, model_class)
            earlier = _duplicate_in_file(raw, model_class, seen, where)
            if earlier:
                row['errors'] = [f"Same id or name as {earlier}"]
        if row['errors']:
            row['status'] = 'error'
        elif row['existing']:
            row['status'] = 'exists'
        else:
            row['status'] = 'new'
    return rows


def plan_import(text, rule_type, source_name=None, detail=True, check=None):
    """
    Check *text* for *rule_type* without writing anything.

    ``source_name`` is the name of the file if there is one, ``detail`` says
    the messages may quote from the text and ``check`` is the rule check of
    the view, called with each loaded document and returning its problems.

    Returns ``{'rows': [...], 'errors': [...], 'notes': [...], 'ok': bool}``:
    a row has ``where``, ``name``, ``status`` (new, exists or error), the
    names in ``existing``, ``errors`` and ``warnings``.
    """
    model_class = _model_class_for(rule_type)
    records, declared, errors = parse_rule_text(text)
    plan = {'rows': [], 'errors': errors, 'notes': [], 'ok': False}
    type_error = _type_error(declared, rule_type, source_name)
    if type_error:
        plan['errors'] = [type_error]
        return plan
    if not declared and _type_of_file_name(source_name) != rule_type:
        plan['notes'].append(
            "The file does not name its rule type. It is only checked against "
            "the fields of this rule type, and some rule types have the same "
            "fields.")
    plan['rows'] = _check_rows(records, model_class, detail, check)
    if not records and not errors:
        plan['errors'] = ["The file holds no rules"]
    plan['ok'] = not plan['errors'] \
        and not any(row['status'] == 'error' for row in plan['rows'])
    return plan


def run_import(plan, rule_type, override=False):
    """
    Write the checked rules of *plan*: an existing rule stays and its record
    is skipped, with *override* the record replaces it, as on the command line.

    Returns the names in ``imported``, ``replaced``, ``skipped``, ``failed``,
    so the page tells exactly what got in, even if the database fails halfway.
    """
    model_class = _model_class_for(rule_type)
    result = {'imported': [], 'replaced': [], 'skipped': [], 'failed': []}
    for row in plan['rows']:
        exists = row['status'] == 'exists'
        if exists and not override:
            result['skipped'].append(row['name'])
            continue
        try:
            status = _save_rule(row['raw'], model_class, override=override,
                                match_name=True)
        except Exception:  # pylint: disable=broad-exception-caught
            status = 'failed'
        if status == 'imported':
            result['replaced' if exists else 'imported'].append(row['name'])
        elif status == 'duplicate':
            result['skipped'].append(row['name'])
        else:
            result['failed'].append(row['name'])
    return result
