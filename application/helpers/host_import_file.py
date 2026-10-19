"""
YAML rows and Secret Store columns for the manual host import.

The host list imports a CSV through a preview where the user picks the
hostname column. YAML (an uploaded file or text pasted into Manual add) goes
through the same preview: a mapping of ``key: value`` pairs is one host, a
list of mappings or several documents separated by ``---`` are several
hosts, and every key becomes a column. Columns the user marks as secret are not written as
labels but into the Secret Store, bound to the imported host.
"""
import json
import re

import yaml

from application.helpers.secret_access import can_bind
from application.models.secret import store_host_secret

YAML_SUFFIXES = ('.yml', '.yaml')

# Column names preselected as secret on the preview.
SECRET_HINTS = ('token', 'password', 'secret', 'certificate', 'cert')


# A first line like ``cluster: name``, ``---`` or ``- key: value``. A
# hostname never holds ``: ``, so a plain hostname list is never taken
# for YAML.
_YAML_START = re.compile(r'^(---|- |[A-Za-z0-9_.-]+:(\s|$))')


def is_yaml_filename(filename):
    """True for a file the import reads as YAML."""
    return (filename or '').lower().endswith(YAML_SUFFIXES)


def looks_like_yaml(text):
    """True when pasted text is YAML rather than hostnames or CSV."""
    for line in (text or '').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        return bool(_YAML_START.match(stripped))
    return False


def _cell(value):
    """A YAML value as the string a CSV cell would hold."""
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _strict_entries(text):
    """Mappings of ``text`` read as real YAML; ValueError when it is not."""
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        raise ValueError(str(exc)) from exc
    entries = []
    for data in documents:
        if data is None:
            continue
        for entry in data if isinstance(data, list) else [data]:
            if not isinstance(entry, dict):
                raise ValueError("expected 'key: value' lines")
            entries.append(entry)
    return entries


# Top-level key of the YAML-like format: ``key: value`` or ``key:``.
_FLAT_KEY = re.compile(r'^([A-Za-z_][\w.-]*):(?:\s+(.*))?$')
_BLOCK_INDICATOR = re.compile(r'^[|>][-+]?$')


def _block_value(indicator, lines):
    """
    Value of a ``key: |`` / ``key: >`` block in the YAML-like format.

    Its lines may carry any indentation (certificate bodies often start at
    column 0 between indented BEGIN/END lines), so every line is stripped
    on the left; a PEM chain comes out as clean, unindented lines.
    """
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    stripped = [line.strip() for line in lines]
    if indicator.startswith('>'):
        value = ' '.join(line for line in stripped if line)
    else:
        value = '\n'.join(stripped)
    if not indicator.endswith('-'):
        value += '\n'
    return value


def _plain_value(value):
    """A plain ``key: value`` value, surrounding quotes removed."""
    value = (value or '').strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


# A ``key: value``, ``key=value`` or ``key<TAB>value`` line of a pasted
# key/value list; split at the first separator, so URLs keep their port.
_KV_LINE = re.compile(r'^\s*([A-Za-z_][\w .-]*?)\s*(?::|=|\t)\s*(.*)$')


def _flat_entries(text, filename, key_value=False):
    """
    Mappings of the YAML-like format: flat ``key: value`` lines, a ``key: |``
    block continues over every following line (whatever its indentation)
    up to the next top-level key, ``---`` separates hosts. Raises
    ValueError naming the first line that fits none of this.

    With ``key_value`` it reads a pasted key/value list instead: lines may
    also be ``key=value`` or ``key<TAB>value`` and an empty line separates
    hosts as well. Inside a block only a ``key:`` line ends it, so base64
    lines ending in ``=`` stay part of a certificate.
    """
    entries, current, block = [], {}, None

    def close_block():
        if block:
            current[block[0]] = _block_value(block[1], block[2])

    def close_host():
        if current:
            entries.append(dict(current))
        current.clear()

    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip() == '---' or (key_value and not line.strip()):
            close_block()
            block = None
            close_host()
            continue
        match = _FLAT_KEY.match(line.rstrip())
        if match is None and key_value and block is None:
            match = _KV_LINE.match(line.rstrip())
        if match:
            close_block()
            block = None
            key, value = match.group(1).strip(), (match.group(2) or '').strip()
            if _BLOCK_INDICATOR.match(value):
                block = (key, value, [])
            else:
                current[key] = _plain_value(value)
            continue
        if block:
            block[2].append(line)
            continue
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        raise ValueError(f"{filename}, line {number}: not a 'key: value' line")
    close_block()
    close_host()
    return entries


def key_value_rows(text, filename='pasted text'):
    """Rows of a pasted key/value list (see ``_flat_entries``)."""
    return [{key: _cell(value) for key, value in entry.items()}
            for entry in _flat_entries(text, filename, key_value=True)]


def yaml_rows(files):
    """
    Rows of the given ``(filename, text)`` YAML files, one dict per host.
    A file may hold several hosts: a list of mappings, or several
    documents separated by ``---`` (each a mapping or a list of them).

    Files that are only YAML-like (block lines out of indentation, as
    certificate chains often come) are read by a tolerant parser for flat
    ``key: value`` files when strict YAML fails. Raises ValueError with a
    short message naming the file and line when both fail.
    """
    rows = []
    for filename, text in files:
        try:
            entries = _strict_entries(text)
        except ValueError:
            entries = _flat_entries(text, filename)
        for entry in entries:
            rows.append({str(key): _cell(value) for key, value in entry.items()})
    return rows


def rows_columns(rows):
    """``(columns, data_rows)`` of row dicts, columns in first-seen order."""
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    data_rows = [[row.get(col, '') for col in columns] for row in rows]
    return columns, data_rows


def suggested_secret_columns(columns, hostname_column):
    """Columns whose name looks like it holds a secret."""
    return [col for col in columns
            if col != hostname_column
            and any(hint in col.lower() for hint in SECRET_HINTS)]


def split_secrets(row, secret_columns):
    """Take the secret columns out of ``row``; returns them as a dict."""
    secrets = {}
    for col in secret_columns:
        value = row.pop(col, None)
        if value not in (None, ''):
            secrets[col] = value
    return secrets


def store_row_secrets(user, host, secrets, source):
    """
    Write ``secrets`` into the Secret Store, bound to ``host``, when
    ``user`` may bind entries to that host. Returns ``(stored, refused)``.
    """
    if not secrets:
        return 0, 0
    if not can_bind(user, host):
        return 0, len(secrets)
    for key, value in secrets.items():
        store_host_secret(host, key, value, source)
    return len(secrets), 0
