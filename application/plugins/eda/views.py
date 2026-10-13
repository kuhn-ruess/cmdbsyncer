"""
Views of Event Driven Ansible
"""
from datetime import datetime

from flask_admin.contrib.mongoengine.filters import FilterEqual, FilterLike
from flask_admin.form import rules as form_rules
from flask_login import current_user
from markupsafe import Markup, escape
from wtforms import HiddenField, StringField, TextAreaField

from application.modules.rule.views import (
    RuleModelView,
    _modern_rule_form,
    div_close,
    div_open,
)
from application.views.default import DefaultModelView

from .models import event_statuses, repeat_states

# Same right as the rest of Ansible: whoever may fire playbooks may send
# events that start them.
EDA_RIGHT = 'ansible'


def _render_eda_outcomes(_view, _context, model, _name):
    """The events of a rule as cards in the list."""
    html = ""
    for entry in model.outcomes:
        extra = ""
        if entry.extra_vars:
            extra = f'<pre class="syncer-code">{escape(entry.extra_vars)}</pre>'
        html += f'''
            <div class="card">
              <div class="card-body">
                <h6 class="card-subtitle mb-2 text-muted">{escape(entry.event)}
                 <small>(resend after {escape(str(entry.resend_after_hours))} h)</small></h6>
                <div class="card-text">{extra}</div>
              </div>
            </div>
            '''
    return Markup(html)


class EdaEventRuleView(RuleModelView):  # pylint: disable=too-many-ancestors
    """
    Editor of the rules deciding which hosts send which events
    """
    column_exclude_list = [
        'conditions', 'outcomes',
    ]

    column_formatters = {
        **RuleModelView.column_formatters,
        'render_eda_outcomes': _render_eda_outcomes,
    }

    column_labels = {
        **RuleModelView.column_labels,
        'render_eda_outcomes': "Events",
    }

    form_overrides = {
        **RuleModelView.form_overrides,
        'render_eda_outcomes': HiddenField,
    }

    form_rules = _modern_rule_form(
        main_fields=[
            form_rules.Field('name'),
            form_rules.Field('documentation'),
            div_open,
            form_rules.NestedRule(('enabled', 'last_match')),
            div_close,
            form_rules.Field('sort_field'),
        ],
        condition_fields=[
            form_rules.Field('condition_typ'),
            form_rules.Field('conditions'),
        ],
        outcome_fields=[form_rules.Field('outcomes')],
        outcome_title='Events',
        outcome_desc='Which event(s) matching hosts send to Event Driven Ansible. '
                     'Extra Vars are YAML key: value pairs, Jinja with the host '
                     'attributes is allowed.',
    )

    form_subdocuments = dict(RuleModelView.form_subdocuments)
    form_subdocuments['outcomes'] = {
        'form_subdocuments': {
            '': {
                'form_overrides': {
                    'event': StringField,
                    'extra_vars': TextAreaField,
                },
                'form_args': {
                    'event': {
                        'description': 'Name the rulebook matches on as '
                                       'event.payload.event, e.g. register_agent_tls',
                    },
                    'extra_vars': {
                        'description': 'YAML, sent as event.payload.vars. '
                                       'Example: os: "{{ os }}"',
                    },
                    'resend_after_hours': {
                        'description': 'Send again after this many hours while '
                                       'the host still matches. 0 sends only once.',
                    },
                },
                'form_widget_args': {
                    'extra_vars': {'rows': 4, 'style': 'font-family: monospace;'},
                },
            },
        },
    }

    def is_accessible(self):
        """Overwrite"""
        return current_user.is_authenticated and current_user.has_right(EDA_RIGHT)


def _status_markup(status):
    """Color-coded outcome of a send."""
    color = {'success': 'green', 'failure': 'red'}.get(status, '#888')
    label = (status or 'unknown').capitalize()
    return Markup(f'<span style="color:{color};font-weight:600;">{escape(label)}</span>')


def _format_status(_v, _c, m, _p):
    """Color-code the outcome of a send."""
    return _status_markup(m.status)


def _format_status_field(_v, _c, m, p):
    """Color-code a status kept in another field."""
    return _status_markup(getattr(m, p, None))


def _format_date(_v, _c, m, p):
    """Format datetime fields."""
    if value := getattr(m, p, None):
        return datetime.strftime(value, "%d.%m.%Y %H:%M:%S")
    return ""


class EdaEventLogView(DefaultModelView):
    """
    Read-only history of the events sent to Event Driven Ansible
    """
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True
    can_view_details = True

    column_extra_row_actions = []  # No clone icon for history rows
    export_types = ['xlsx', 'csv']
    page_size = 50

    column_default_sort = ('sent_at', True)

    column_list = (
        'sent_at', 'hostname', 'event', 'rule_name', 'account',
        'status', 'http_status',
    )
    column_sortable_list = column_list

    column_filters = (
        FilterLike('hostname', 'Host'),
        FilterLike('event', 'Event'),
        FilterLike('rule_name', 'Rule'),
        FilterLike('account', 'Account'),
        FilterEqual('status', 'Status', options=event_statuses),
    )

    column_formatters = {
        'sent_at': _format_date,
        'status': _format_status,
    }

    column_details_list = (
        'sent_at', 'hostname', 'event', 'rule_name', 'rule_id', 'account',
        'status', 'http_status', 'payload', 'response',
    )

    column_formatters_detail = {
        'sent_at': _format_date,
        'status': _format_status,
    }

    def is_accessible(self):
        """Overwrite"""
        return current_user.is_authenticated and current_user.has_right(EDA_RIGHT)


def _format_repeat_state(_v, _c, m, _p):
    """Color-code the streak of an event."""
    color = {'repeating': 'red', 'pending': 'orange', 'resolved': 'green'}.get(m.state, '#888')
    label = (m.state or 'unknown').capitalize()
    return Markup(f'<span style="color:{color};font-weight:600;">{escape(label)}</span>')


class EdaEventStateView(DefaultModelView):
    """
    Read-only overview of how often each host was sent each event while
    it kept matching. Repeating streaks are the ones without effect.
    """
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True
    can_view_details = True

    column_extra_row_actions = []  # No clone icon for state rows
    export_types = ['xlsx', 'csv']
    page_size = 50

    column_default_sort = ('sends', True)

    column_list = (
        'state', 'hostname', 'event', 'rule_name', 'account', 'sends',
        'failures', 'repeat_threshold', 'first_sent', 'last_sent',
        'last_status', 'resolved_at',
    )
    column_sortable_list = column_list

    column_labels = {
        'sends': 'Sends (streak)',
        'failures': 'Failed sends',
        'repeat_threshold': 'Threshold',
    }

    column_filters = (
        FilterEqual('state', 'State', options=repeat_states),
        FilterLike('hostname', 'Host'),
        FilterLike('event', 'Event'),
        FilterLike('rule_name', 'Rule'),
        FilterLike('account', 'Account'),
        FilterEqual('last_status', 'Last Status', options=event_statuses),
    )

    column_formatters = {
        'state': _format_repeat_state,
        'last_status': _format_status_field,
        'first_sent': _format_date,
        'last_sent': _format_date,
        'resolved_at': _format_date,
    }

    column_details_list = column_list + ('total_sends', 'last_http_status',
                                         'last_match', 'rule_id')

    column_formatters_detail = {
        **column_formatters,
        'last_match': _format_date,
    }

    def is_accessible(self):
        """Overwrite"""
        return current_user.is_authenticated and current_user.has_right(EDA_RIGHT)
