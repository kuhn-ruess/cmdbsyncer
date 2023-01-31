"""
Netbox Rule Views
"""
from markupsafe import Markup
from wtforms import HiddenField

from application.modules.rule.views import RuleModelView
from application.modules.netbox.models import netbox_outcome_types

def _render_netbox_outcome(_view, _context, model, _name):
    """
    Render Netbox outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{dict(netbox_outcome_types)[entry.action]}</td>"
        if entry.param:
            html += f"<td><b>{entry.param}</b></td></tr>"
    html += "</table>"
    return Markup(html)


#pylint: disable=too-few-public-methods
class NetboxCustomAttributesView(RuleModelView):
    """
    Custom Rule Model View
    """
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

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        self.column_formatters.update({
            'render_netbox_outcome': _render_netbox_outcome,
        })

        self.form_overrides.update({
            'render_netbox_outcome': HiddenField,
        })

        self.column_labels.update({
            'render_netbox_outcome': "Netbox Actions",
        })

        super().__init__(model, **kwargs)
