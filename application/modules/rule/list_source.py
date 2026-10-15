"""
List Source of a rule

A rule can take a pasted table (CSV, semicolon separated or a block copied
out of a spreadsheet, which arrives tab separated) as its input instead of
the hosts. Its first line names the columns; every further line is one
row. The export renders the rule's outcomes once per row, with the row's
columns available as Jinja variables, instead of once per host.

Shared by every rule type that offers it: the model part lives in
``application.modules.rule.models`` (``ListSourceMixin``), the form part in
``application.modules.rule.list_source_views``. What a row turns into stays
with the export of the rule type.

Kept free of Flask and Mongo so the parser can be used by the export, the
form validation and the form preview alike.
"""
import csv
import io
import re
from collections import namedtuple

import jinja2
from jinja2 import meta

# Delimiters a pasted list may use, in the order they are preferred when
# the first line contains more than one of them.
DELIMITERS = ('\t', ';', ',', '|')

# Upper bound for one list. A rule with more rows than this belongs
# into an import, not into a text field.
MAX_ROWS = 10000

# The two ways a rule can get its input. Stored on the rule as
# ``rule_source``; a rule saved before the switch existed has none.
RULE_SOURCE_HOSTS = 'hosts'
RULE_SOURCE_LIST = 'list'
RULE_SOURCE_CHOICES = (
    (RULE_SOURCE_HOSTS, 'Per host (default): rendered for every matching host'),
    (RULE_SOURCE_LIST, 'From a pasted list: rendered once per row of the list'),
)

# Names every row template sees besides the columns (see ``row_context``
# and the loop of an outcome).
ROW_NAMES = ('row', 'row_idx', 'loop', 'loop_idx', 'HOSTNAME')

# Columns that name the object a row stands for, in the order they are
# read (see ``row_name``).
NAME_COLUMNS = ('hostname', 'name')

ParsedList = namedtuple('ParsedList', ['columns', 'rows', 'errors', 'delimiter'])


def rule_uses_list(rule_source, list_text):
    """
    Whether a rule is rendered from its list instead of per host.

    The rule's mode decides. Only a rule without a mode (saved before the
    switch existed) falls back to whether its list field is filled.
    """
    if rule_source:
        return rule_source == RULE_SOURCE_LIST
    return bool((list_text or '').strip())


def is_list_rule(rule):
    """``rule_uses_list`` for a rule document with a list source."""
    return rule_uses_list(getattr(rule, 'rule_source', None),
                          getattr(rule, 'list_source', None))


def column_name(header):
    """
    Turn a header cell into the name of its Jinja variable: lower case,
    every run of characters that may not appear in a name becomes one
    underscore, and a leading digit gets an underscore in front.

    ``Service Level`` → ``service_level``, ``2nd Team`` → ``_2nd_team``.
    """
    name = re.sub(r'[^0-9a-zA-Z_]+', '_', header.strip()).strip('_').lower()
    if name and name[0].isdigit():
        name = f'_{name}'
    return name


def detect_delimiter(first_line):
    """
    The delimiter of a list, read from its header line: the candidate the
    line contains most often wins, ties go to the earlier one in
    ``DELIMITERS``. A header without any of them is a single column list,
    read as comma separated.
    """
    best = ','
    best_count = 0
    for candidate in DELIMITERS:
        count = first_line.count(candidate)
        if count > best_count:
            best, best_count = candidate, count
    return best


def _header_columns(header):
    """
    Variable names of the header cells and the cell position each one is
    read from, plus the problems found on the way. A cell left empty drops
    its column.
    """
    columns = []
    positions = []
    errors = []
    for pos, cell in enumerate(header):
        name = column_name(cell)
        if not name:
            if cell.strip():
                errors.append(f"Header column {pos + 1} ('{cell.strip()}') "
                              "gives no usable variable name")
            continue
        if name in columns:
            errors.append(f"Header column {pos + 1}: the variable name "
                          f"'{name}' is used twice")
            continue
        columns.append(name)
        positions.append(pos)
    if not columns:
        errors.append("The first line has to name the columns")
    return columns, positions, errors


# pylint: disable-next=too-many-locals
def parse_list_source(text, max_rows=MAX_ROWS):
    """
    Parse a pasted list into ``ParsedList(columns, rows, errors, delimiter)``.

    ``columns`` are the variable names of the header line, ``rows`` one
    dict per data line (column name → stripped cell text). Quoted cells may
    contain the delimiter and line breaks. Empty lines are skipped, a
    header cell left empty drops its column, a line shorter than the
    header is filled up with empty cells. ``errors`` lists everything that
    makes the list unusable; when it is not empty, the export does not use
    the list at all.
    """
    text = (text or '').strip('\r\n')
    if not text.strip():
        return ParsedList([], [], [], None)
    delimiter = detect_delimiter(text.splitlines()[0])
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        lines = [(reader.line_num, cells) for cells in reader]
    except csv.Error as error:
        return ParsedList([], [], [f"The list could not be read: {error}"],
                          delimiter)

    columns, positions, errors = _header_columns(lines[0][1])
    header = lines[0][1]

    rows = []
    for line_num, cells in lines[1:]:
        if not any(cell.strip() for cell in cells):
            continue
        extra = [(pos, cell) for pos, cell in enumerate(cells)
                 if pos >= len(header) and cell.strip()]
        if extra:
            pos, cell = extra[0]
            errors.append(
                f"Line {line_num}: cell {pos + 1} ('{_short(cell)}') has no "
                f"column, the first line names only {len(header)} "
                f"columns ({', '.join(columns)}). Check the separator or quote "
                "the cell")
            continue
        rows.append({
            name: (cells[pos].strip() if pos < len(cells) else '')
            for name, pos in zip(columns, positions)
        })
    if len(rows) > max_rows:
        errors.append(f"The list has {len(rows)} rows, at most {max_rows} "
                      "are supported")
    return ParsedList(columns, rows, errors, delimiter)


def _short(text, limit=40):
    """A cell shortened for an error message."""
    text = ' '.join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}..."


def template_variables(template):
    """
    The variables a Jinja template reads, or an empty set when the template
    cannot be parsed (its syntax is checked elsewhere) or uses an
    ``{{ACCOUNT:...}}`` macro, which is resolved before Jinja sees it.
    """
    if not template or '{' not in template or 'ACCOUNT:' in template:
        return set()
    try:
        return meta.find_undeclared_variables(jinja2.Environment().parse(template))
    except jinja2.TemplateSyntaxError:
        return set()


def outcome_templates(data, template_fields):
    """
    The ``(label, template)`` pairs of submitted outcome fields, read from
    form data keyed ``outcomes-<n>-<field>`` (the names the rule forms
    use), in outcome order. ``template_fields`` are the ``(field, label)``
    pairs of the rule type's outcome fields that are rendered per row.
    Labels count outcomes from 1 as the form shows them.
    """
    fields = dict(template_fields)
    found = []
    for key, value in data.items():
        match = re.fullmatch(r'outcomes-(\d+)-(\w+)', key)
        if not match or match.group(2) not in fields or not value:
            continue
        found.append((int(match.group(1)), match.group(2), value))
    order = [name for name, _label in template_fields]
    found.sort(key=lambda item: (item[0], order.index(item[1])))
    positions = sorted({idx for idx, _field, _value in found})
    return [(f"Outcome {positions.index(idx) + 1}, {fields[field]}", value)
            for idx, field, value in found]


def check_list_rule(rule_source, list_text, templates, known_names=()):
    """
    Check a rule's mode, list and outcome templates as it is saved.

    ``templates`` are ``(label, template)`` pairs, e.g.
    ``('Outcome 1, Value', '{{ level }}')``; ``known_names`` the Jinja
    globals that are not columns. Returns ``(parsed, errors, warnings)``:
    errors make the list unusable, warnings name templates reading a
    variable that is no column of the list (it renders empty). A rule
    rendered per host is not checked at all.
    """
    if not rule_uses_list(rule_source, list_text):
        return ParsedList([], [], [], None), [], []
    parsed = parse_list_source(list_text)
    errors = [f"List: {error}" for error in parsed.errors]
    if not (list_text or '').strip():
        errors.append("List: the rule source is 'From a pasted list', but "
                      "the list is empty. Paste a list or switch the rule "
                      "source back to 'Per host'")
    warnings = []
    if parsed.columns:
        known = set(parsed.columns) | set(ROW_NAMES) | set(known_names)
        columns = ', '.join(f'{{{{ {name} }}}}' for name in parsed.columns)
        for label, template in templates:
            for name in sorted(template_variables(template) - known):
                warnings.append(
                    f"{label}: '{{{{ {name} }}}}' is not a column of the "
                    f"list, it renders empty. "
                    f"Columns: {columns}")
    return parsed, errors, warnings


def row_name(row):
    """
    The name of the object a row stands for, where the target of a rule
    needs one (an i-doit object, a Netbox device, a host in Checkmk, ...):
    the row's ``hostname`` column, else its ``name`` column. None when
    the row has neither or leaves them empty.
    """
    for column in NAME_COLUMNS:
        if row.get(column):
            return row[column]
    return None


def row_context(row, row_idx):
    """
    The Jinja context of one row: every column as a variable of its own,
    the whole row as ``row`` (for names that collide with a Jinja keyword)
    and its 0-based position as ``row_idx``. ``HOSTNAME`` is explicitly
    None, like for any host-independent rule.
    """
    context = dict(row)
    context['row'] = dict(row)
    context['row_idx'] = row_idx
    context['HOSTNAME'] = None
    return context
