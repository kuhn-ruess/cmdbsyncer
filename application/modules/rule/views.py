"""
Rule Model View
"""
from wtforms import HiddenField
from flask_login import current_user
from markupsafe import Markup
from application.views.default import DefaultModelView
from application.modules.rule.models import filter_actions

#   .-- Renderer
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

def _render_filter_outcomes(_view, _context, model, _name):
    """
    Render Filter outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{dict(filter_actions)[entry.action]}</td>"
        if entry.attribute_name:
            html += f"<td><b>{entry.attribute_name}</b></td></tr>"
        else:
            html += "<td></td></tr>"

    html += "</table>"
    return Markup(html)


def _render_label_outcomes(_view, _context, model, _name):
    """
    Render Label outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{entry.label_name}</td>"\
                f"<td><b>{entry.label_value}</b></td></tr>"
    html += "</table>"
    return Markup(html)

def _render_host_conditions(_view, _context, model, _name):
    """
    Condition for Host Params
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.conditions):
        line = f"<tr><td>{idx}</td>"\
               f"<td><b>Hostname</b></td><td>"
        if entry.match_negate:
            line += "<b>NOT</b> "
        line += f"{condition_types[entry.match]}</td>"\
                f"<td><b>{entry.hostname}</b></td></tr>"
        html += line
    html += "</table>"
    return Markup(html)

def _render_full_conditions(_view, _context, model, _name):
    """
    Render full condition set which contains host or labels
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.conditions):
        if entry.match_type == 'host':
            html += f"<tr><td>{idx}</td> <td><b>Hostname</b></td><td>"
            if entry.hostname_match_negate:
                html += "<b>NOT</b> "
            html += f"{condition_types[entry.hostname_match]}</td>"\
                    f"<td><b>{entry.hostname}</b></td></tr>"
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

def _render_label_conditions(_view, _context, model, _name):
    """
    Render Label Conditions
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.conditions):
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

#.
#   .-- Rule Model
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
        'render_full_conditions': _render_full_conditions,
        'render_host_conditions': _render_host_conditions,
        'render_label_outcomes': _render_label_outcomes,
        'render_label_conditions': _render_label_conditions,
        #'render_host_params': _render_host_params,
    }

    form_overrides = {
        'render_full_conditions': HiddenField,
        'render_host_conditions': HiddenField,
        'render_label_outcomes': HiddenField,
        'render_label_conditions': HiddenField,
        #'render_host_params': HiddenField,
    }

    column_labels = {
        'render_full_conditions': "Conditions",
        'render_host_conditions': "Host Conditions",
        'render_label_outcomes': "New Labels",
        'render_label_conditions': "Label Conditions",
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('rule')

#.
#   .-- Filter
#pylint: disable=too-few-public-methods
class FiltereModelView(DefaultModelView):
    """
    Filter
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
        'render_full_conditions': _render_full_conditions,
        'render_filter_outcome': _render_filter_outcomes,
    }

    form_overrides = {
        'render_filter_outcome': HiddenField,
        'render_full_conditions': HiddenField,
    }

    column_labels = {
        'render_filter_outcome': "Filter Parameters",
        'render_full_conditions': "Conditions",
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('rule')
#.
#   .-- Rewrite Labels
def _render_label_rewrite(_view, _context, model, _name):
    """
    Render Label outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{entry.old_label_name}</td>"\
                 "<td><b>to</b></td>"\
                f"<td>{entry.new_label_name}</td></tr>"
    html += "</table>"
    return Markup(html)


#pylint: disable=too-few-public-methods
class RewriteLabelView(RuleModelView):
    """
    Custom Label Model View
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        self.column_formatters.update({
            'render_label_rewrite': _render_label_rewrite,
        })

        self.form_overrides.update({
            'render_label_rewrite': HiddenField,
        })

        self.column_labels.update({
            'render_label_rewrite': "Label Rewrites",
        })

        super().__init__(model, **kwargs)
#.
