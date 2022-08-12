"""
Rule Model View
"""
from wtforms import HiddenField
from flask_login import current_user
from application.views.default import DefaultModelView
from markupsafe import Markup

def _render_outcome(_view, _context, model, name):
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcome):
        value = ""
        if entry.param:
            value = entry.param
            if hasattr(entry, 'value'):
                value +=f":{entry.value}"
        html += f"<tr><td>{idx}</td><td>{entry.type}</td><td>{value}</td></tr>"
    html += "</table>"
    return Markup(html)

def _render_conditions(_view, _context, model, name):
    html = "<table width=100%>"
    for idx, entry in enumerate(model.conditions):
        if entry.match_type == 'host':
            html += f"<tr><td>{idx} Host</td><td>{entry.hostname_match}</td>"\
                    f"<td>{entry.hostname}</td><td>{entry.hostname_match_negate}</td></tr>"
        else:
            html += f"<tr><td>{idx} Label</td><td colspan=3>"\
                "<table>"\
                "<tr>"\
                "<td>Tag</td>"\
                f"<td><b>{entry.tag_match}</b></td>"\
                f"<td>{entry.tag}</td>"\
                f"<td><b>{entry.tag_match_negate}</b></td>"\
                "</tr>"\
                "<tr>"\
                "<td>Value</td>"\
                f"<td><b>{entry.value_match}</b></td>"\
                f"<td>{entry.value}</td>"\
                f"<td><b>{entry.value_match_negate}</b></td>"\
                "</tr>"\
                "</table>"\
                "</td></tr>"
    html += "</table>"
    return Markup(html)

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
    }

    form_overwrites = {
        'render_outcome': HiddenField,
        'render_conditions': HiddenField,
    }

    column_labels = {
        'render_outcome': "Outcome",
        'render_conditions': "Condition",
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('rule')
