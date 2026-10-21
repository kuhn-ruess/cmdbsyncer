"""
Building blocks shared by every Checkmk configuration check: the check base
class, the finding a check reports and the helpers to read rules.
"""
import ast
import json
from dataclasses import dataclass, field
from datetime import datetime

SEVERITY_WARNING = 'warning'
SEVERITY_INFO = 'info'


@dataclass(frozen=True)
class Column:
    """
    One column of a topic's table. ``key`` names the finding value shown in
    it, ``kind`` how: ``text``, ``code``, ``state`` (a WARN/CRIT/UNKNOWN
    badge) or ``items`` (a list of rule items, see :class:`Finding`).
    """
    key: str
    label: str
    kind: str = 'text'


@dataclass(frozen=True)
class Topic:
    """
    One kind of problem a check reports. The report gets a section per
    topic: ``title`` and the number of findings as heading, ``description``
    (what it means), ``action`` (what to do) and a table with ``columns``.
    """
    key: str
    title: str
    description: str
    action: str
    columns: tuple
    severity: str = SEVERITY_WARNING


@dataclass
class Finding:
    """
    One problem a check found, filed under the topic called ``topic``.
    ``values`` holds the cells of the topic's columns by column key. An
    ``items`` column holds a list of dicts with the keys ``service``,
    ``rule``, ``rule_id``, ``folder`` and ``detail`` (missing keys render
    empty): the rules or rule parts involved.
    """
    topic: str
    values: dict = field(default_factory=dict)


class ConfigCheck:
    """
    Base class of a configuration check.

    A subclass sets ``name`` (stable id, used in forms and URLs), ``title``,
    ``description`` and ``topics`` (the :class:`Topic` list, in report
    order) and implements :meth:`analyze`, which gets the Checkmk
    connection and returns ``(findings, stats)``: a list of
    :class:`Finding` and a list of ``(label, value)`` pairs describing what
    was looked at. Keep the I/O in a thin fetch step and the analysis pure,
    so it can be tested without Checkmk.
    """
    name = ''
    title = ''
    description = ''
    topics = ()

    def analyze(self, cmk):
        """Read from ``cmk`` and return ``(findings, stats)``."""
        raise NotImplementedError

    def sections(self, findings):
        """
        The findings grouped by topic: one ``{'topic', 'findings'}`` dict per
        declared topic, in declared order, empty topics included. A finding
        of an undeclared topic is a programming error and raises ValueError.
        """
        by_topic = {topic.key: [] for topic in self.topics}
        for finding in findings:
            if finding.topic not in by_topic:
                raise ValueError(f"{self.name}: undeclared topic '{finding.topic}'")
            by_topic[finding.topic].append(finding)
        return [{'topic': topic, 'findings': by_topic[topic.key]}
                for topic in self.topics]

    def run(self, cmk, account_name):
        """Run the check and wrap its result into a report dict."""
        findings, stats = self.analyze(cmk)
        sections = self.sections(findings)
        return {
            'name': self.name,
            'title': self.title,
            'description': self.description,
            'account': account_name,
            'run_at': datetime.now(),
            'stats': stats,
            'sections': sections,
            'total': len(findings),
            'warnings': sum(len(section['findings']) for section in sections
                            if section['topic'].severity == SEVERITY_WARNING),
        }


def parse_rule(cmk_rule):
    """
    Flatten one rule of a REST API rule collection into ``{'id', 'folder',
    'description', 'comment', 'disabled', 'conditions', 'value'}``.
    ``value`` is the parsed ``value_raw``; None when it cannot be parsed.
    """
    # pylint: disable=import-outside-toplevel
    from ..cmk_rules import normalize_cmk_folder
    extensions = cmk_rule.get('extensions', {}) or {}
    properties = extensions.get('properties', {}) or {}
    try:
        value = ast.literal_eval(extensions.get('value_raw') or '')
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        value = None
    return {
        'id': cmk_rule.get('id', ''),
        'folder': normalize_cmk_folder(extensions.get('folder', '/')),
        'description': properties.get('description', '') or '',
        'comment': properties.get('comment', '') or '',
        'disabled': bool(properties.get('disabled', False)),
        'conditions': extensions.get('conditions', {}) or {},
        'value': value,
    }


def fetch_rules(cmk, ruleset_name):
    """
    Every rule of ``ruleset_name`` on the site, parsed with
    :func:`parse_rule`. A ruleset the site does not know returns an empty
    list (the REST API answers 404).
    """
    response, _headers = cmk.request(
        f"domain-types/rule/collections/all?ruleset_name={ruleset_name}",
        method="GET")
    return [parse_rule(rule) for rule in response.get('value', []) or []]


def clean_conditions(conditions):
    """The conditions without the keys that hold no restriction."""
    return {key: value for key, value in (conditions or {}).items() if value}


def condition_key(conditions):
    """A hashable, order independent form of a rule's conditions."""
    return json.dumps(clean_conditions(conditions), sort_keys=True)


def _describe_host_name(value):
    names = ', '.join(str(name) for name in value.get('match_on', []))
    if value.get('operator') == 'none_of':
        return f"host name not {names}"
    return f"host name {names}"


def _describe_tags(value):
    parts = []
    for tag in value:
        operator = tag.get('operator', 'is')
        tag_value = tag.get('value')
        if isinstance(tag_value, dict):
            tag_value = ' / '.join(str(v) for v in tag_value.get('value', []))
        parts.append(f"tag {tag.get('key')} {operator.replace('_', ' ')} {tag_value}")
    return ', '.join(parts)


def _describe_label_groups(prefix, groups):
    labels = []
    for group in groups:
        for label in group.get('label_group', []):
            negate = 'not ' if label.get('operator') == 'not' else ''
            labels.append(f"{negate}{label.get('label')}")
    return f"{prefix} {', '.join(labels)}"


def describe_conditions(conditions):
    """
    A short readable text of a rule's conditions, e.g.
    ``host name srv01, srv02; tag criticality is prod``. No conditions
    reads ``all hosts``.
    """
    conditions = clean_conditions(conditions)
    if not conditions:
        return 'all hosts'
    parts = []
    for key in sorted(conditions):
        value = conditions[key]
        if key == 'host_name' and isinstance(value, dict):
            parts.append(_describe_host_name(value))
        elif key == 'host_tags' and isinstance(value, list):
            parts.append(_describe_tags(value))
        elif key.endswith('label_groups') and isinstance(value, list):
            prefix = 'service labels' if key.startswith('service') else 'host labels'
            parts.append(_describe_label_groups(prefix, value))
        else:
            parts.append(f"{key} {json.dumps(value, sort_keys=True)}")
    return '; '.join(parts)
