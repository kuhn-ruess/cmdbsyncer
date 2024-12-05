"""
Netbox Rule Views
"""
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DjangoLexer

from markupsafe import Markup
from wtforms import HiddenField, StringField

from application.views.default import DefaultModelView
from application.modules.rule.views import RuleModelView
from application.modules.netbox.models import (netbox_outcome_types,
                                               netbox_ipam_ipaddress_outcome_types,
                                               netbox_device_interface_outcome_types,
                                               netbox_contact_outcome_types,
                                               NetboxDataflowAttributes
                                              )

def _render_netbox_outcome(_view, _context, model, _name):
    """
    Render Netbox outcomes
    """
    html = "<table width=100%>"
    outcome_names = netbox_outcome_types + netbox_ipam_ipaddress_outcome_types
    outcome_names +=  netbox_device_interface_outcome_types
    outcome_names +=  netbox_contact_outcome_types
    for idx, entry in enumerate(model.outcomes):
        if entry.param:
            highlighted_param = \
                    highlight(entry.param, DjangoLexer(), HtmlFormatter(sytle='colorfull'))
        html += f"<tr><td>{idx}</td><td>{dict(outcome_names)[entry.action]}</td>"
        if entry.param:
            html += f"<td><b>{highlighted_param}</b></td></tr>"
    html += "</table>"
    return Markup(html)


#pylint: disable=too-few-public-methods
class NetboxCustomAttributesView(RuleModelView):
    """
    Custom Rule Model View
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        self.column_formatters.update({
            'render_netbox_outcome': _render_netbox_outcome
        })

        self.form_overrides.update({
            'render_netbox_outcome': HiddenField,
        })

        self.column_labels.update({
            'render_netbox_outcome': "Netbox Actions",
        })
        #pylint: disable=access-member-before-definition
        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments' : {
                    '': {
                        'form_overrides' : {
                            #'param': StringField,
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)

def _render_dataflow_outcome(_view, _context, model, _name):
    """
    Render Dataflow outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        highlighted_param = highlight(entry.field_value,
                                      DjangoLexer(),
                                      HtmlFormatter(sytle='colorfull'))
        html += f"<tr><td>{idx}</td><td>{entry.field_name}</td>"
        html += f"<td><b>{highlighted_param}</b></td></tr>"
    html += "</table>"
    return Markup(html)

class NetboxDataFlowAttributesView(RuleModelView):
    """
    Custom Dataflow Model
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        self.column_formatters.update({
            'render_netbox_outcome': _render_dataflow_outcome,
        })

        self.form_overrides.update({
            'render_netbox_outcome': HiddenField,
        })

        self.column_labels.update({
            'render_netbox_outcome': "Netbox Actions",
        })

        #pylint: disable=access-member-before-definition
        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments' : {
                    '': {
                        'form_overrides' : {
                            #'param': StringField,
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)

class NetboxDataFlowModelView(DefaultModelView):
    """
    Custom Dataflow Model Model View :-)
    """
