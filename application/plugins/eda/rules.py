"""
Rule engine of Event Driven Ansible: which events a host sends
"""
import yaml

from application.modules.rule.rule import Rule
from application.helpers.syncer_jinja import render_jinja

from .models import DEFAULT_RESEND_HOURS


def render_extra_vars(template, attributes):
    """
    The `vars` of an event: the outcome's YAML after rendering its Jinja
    with the host attributes. An empty field means no vars. Raises
    ValueError when the result is not a YAML mapping, so a typo shows up
    as a failed event instead of an event with garbage in it.
    """
    if not (template or '').strip():
        return {}
    # Newlines are what separates the YAML lines, so they have to stay
    rendered = render_jinja(template, replace_newlines=False, _ctx=attributes)
    try:
        data = yaml.safe_load(rendered)
    except yaml.YAMLError as exc:
        raise ValueError(f"Extra vars are no valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Extra vars must be YAML key: value pairs")
    return data


def resend_hours(value):
    """Hours until an event is sent again, the default for a missing value."""
    if value is None or value == '':
        return DEFAULT_RESEND_HOURS
    return max(int(value), 0)


class EdaEventRuleEngine(Rule):
    """
    Collects the events of every matching rule under `events`, one entry
    per outcome, with its vars already rendered for the host.
    """

    name = "Event Driven Ansible -> Events"

    def add_outcomes(self, rule, rule_outcomes, outcomes):
        """Add one event per outcome of a matching rule."""
        events = outcomes.setdefault('events', [])
        for outcome in rule_outcomes:
            event_name = render_jinja(outcome.get('event') or '',
                                      _ctx=self.attributes).strip()
            if not event_name:
                continue
            entry = {
                'rule_id': str(rule['_id']),
                'rule_name': rule['name'],
                'event': event_name,
                'resend_after_hours': resend_hours(outcome.get('resend_after_hours')),
                'vars': {},
                'error': None,
            }
            try:
                entry['vars'] = render_extra_vars(outcome.get('extra_vars'), self.attributes)
            except ValueError as exc:
                entry['error'] = str(exc)
            events.append(entry)
        return outcomes
