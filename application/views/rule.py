"""
Rule Model View
"""
from wtforms import HiddenField
from flask_login import current_user
from markupsafe import Markup
from application.views.default import DefaultModelView
from application.models.rule import label_choices, label_outcome_types, \
                                    host_params_types, action_outcome_types
from application.models.ansible_rule import ansible_outcome_types, ansible_outcome_rule_types
from application.models.netbox_rule import netbox_outcome_types
from application.models.label_overwrite_rule import label_overwrite_outcome_types

condition_types={
    'equal': "is equal",
    'in': "contains",
    'in_list': "found in list",
    'ewith': "endswith",
    'swith': "startswith",
    'regex': "regex match",
    'bool': "Boolean",
    'ignore': "always match",
}

action_outcome_types = dict(action_outcome_types)
action_outcome_types.update(dict(ansible_outcome_types))
action_outcome_types.update(dict(ansible_outcome_rule_types))
action_outcome_types.update(dict(netbox_outcome_types))
action_outcome_types.update(dict(label_overwrite_outcome_types))

def _render_outcome(_view, _context, model, _name):
    """
    Render General outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcome):
        value = ""
        if hasattr(entry, 'param'):
            value = entry.param
            if hasattr(entry, 'value'):
                value +=f":{entry.value}"
        elif hasattr(entry, 'value'):
            value = entry.value
        html += f"<tr><td>{idx}</td><td>{action_outcome_types[entry.type]}</td>"\
                f"<td><b>{value}</b></td></tr>"
    html += "</table>"
    return Markup(html)

def _render_host_conditions(_view, _context, model, _name):
    """
    Condition for Host Params
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.conditions):
        html += f"<tr><td>{idx}</td>"\
                f"<td><b>Hostname</b></td><td>{condition_types[entry.match]}</td>"\
                f"<td><b>{entry.hostname}</b></td><td>Negate:<b>{entry.match_negate}</b></td></tr>"
    html += "</table>"
    return Markup(html)


label_choices = dict(label_choices)

def _render_label_conditions(_view, _context, model, _name):
    """
    Render all Condtions who based on labels only
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.conditions):
        html += "<tr>"\
                f"<td>{idx}</td>"\
                f"<td><b>{label_choices[entry.match_on]}</b></td>"\
                f"<td>{entry.match}</td>"\
                f"<td><b>{entry.value}</b></td>"\
                f"<td>Negate: <b>{entry.match_negate}</b></td>"\
                "</tr>"
    html += "</table>"
    return Markup(html)


label_outcome_types = dict(label_outcome_types)

def _render_label_outcomes(_view, _context, model, _name):
    """
    Render Outcomes for label rule
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcome):
        html += f"<tr><td>{idx}</td> <td>{label_outcome_types[entry]}</td></tr>"
    html += "</table>"
    return Markup(html)

host_params_types = dict(host_params_types)
def _render_host_params(_view, _context, model, _name):
    """
    Render Params of host
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.params):
        html += f"<tr><td>{idx}</td> <td>{host_params_types[entry.type]}</td>"\
                f"<td><b>{entry.name}</b></td><td><b>{entry.value}</b></td></tr>"
    html += "</table>"
    return Markup(html)

def _render_conditions(_view, _context, model, _name):
    """
    Render full condition set which contains host or labels
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.conditions):
        if entry.match_type == 'host':
            html += f"<tr><td>{idx}</td> <td><b>Hostname</b></td>"\
                    f"<td>{condition_types[entry.hostname_match]}</td>"\
                    f"<td><b>{entry.hostname}</b></td>"\
                    f"<td>Negate: <b>{entry.hostname_match_negate}</b></td></tr>"
        else:
            html += f"<tr><td>{idx}</td><td><b>Label</b></td><td>"\
                "<table width=100%>"\
                "<tr>"\
                "<td><b>Key</b></td>"\
                f"<td>{condition_types[entry.tag_match]}</td>"\
                f"<td><b>{entry.tag}</b></td>"\
                f"<td>Negate: <b>{entry.tag_match_negate}</b></td>"\
                "</tr>"\
                "<tr>"\
                "<td><b>Value</b></td>"\
                f"<td>{condition_types[entry.value_match]}</td>"\
                f"<td><b>{entry.value}</b></td>"\
                f"<td>Negate: <b>{entry.value_match_negate}</b></td>"\
                "</tr>"\
                "</table>"\
                "</td></tr>"
    html += "</table>"
    return Markup(html)


#pylint: disable=too-few-public-methods
class RuleModelView(DefaultModelView):
    """
    Rule Model
    """

    column_default_sort = "sort_field"
    column_filters = (
       'name',
       'enabled',
    )
    form_subdocuments = {
        'conditions': {
            'form_subdocuments' : {
                None: {
                    'form_widget_args': {
                        'hostname_match': { 'style': 'background-color: #2EFE9A' },
                        'hostname': { 'style': 'background-color: #2EFE9A' },
                        'tag_match': { 'style': 'background-color: #81DAF5' },
                        'tag': { 'style': 'background-color: #81DAF5' },
                        'value_match': { 'style': 'background-color: #81DAF5' },
                        'value': { 'style': 'background-color: #81DAF5' },
                    },
                }
            }
        }
    }

    column_formatters = {
        'render_outcome': _render_outcome,
        'render_conditions': _render_conditions,
        'render_host_conditions': _render_host_conditions,
        'render_label_conditions': _render_label_conditions,
        'render_host_params': _render_host_params,
        'outcome': _render_label_outcomes,
    }

    form_overrides = {
        'render_outcome': HiddenField,
        'render_conditions': HiddenField,
        'render_host_conditions': HiddenField,
        'render_host_params': HiddenField,
        'render_label_conditions': HiddenField,
    }

    column_labels = {
        'render_outcome': "Outcome",
        'render_conditions': "Condition",
        'render_host_conditions': "Condition",
        'render_label_conditions': "Condition",
        'render_host_params': "Parameter",
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('rule')
