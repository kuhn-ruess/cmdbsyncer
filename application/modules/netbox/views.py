"""
Netbox Rule Views
"""
from datetime import datetime
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DjangoLexer

from markupsafe import Markup
from wtforms import HiddenField, StringField

from application.views.default import DefaultModelView
from application.modules.rule.views import RuleModelView, get_rule_json
from application.modules.netbox.models import (netbox_outcome_types,
                                               netbox_ipam_ipaddress_outcome_types,
                                               netbox_device_interface_outcome_types,
                                               netbox_contact_outcome_types,
                                               netbox_cluster_outcomes,
                                               netbox_virtualmachines_types,
                                               netbox_prefix_outcome_types,
                                              )

def _render_netbox_outcome(_view, _context, model, _name):
    """
    Render Netbox outcomes
    """
    html = ""
    outcome_names = netbox_outcome_types + netbox_ipam_ipaddress_outcome_types
    outcome_names += netbox_device_interface_outcome_types
    outcome_names += netbox_contact_outcome_types
    outcome_names += netbox_cluster_outcomes
    outcome_names += netbox_virtualmachines_types
    outcome_names += netbox_prefix_outcome_types

    for entry in model.outcomes:
        name = dict(outcome_names).get(entry.action, "Field deprecated")
        highlighted_param = ""
        if entry.param:
            highlighted_param = \
                    highlight(entry.param, DjangoLexer(), HtmlFormatter(sytle='colorfull'))
        html += f'''
            <div class="card">
              <div class="card-body">
                <p class="card-text">
                 <h6 class="card-subtitle mb-2 text-muted">{name}</h6>
                </p>
                <p class="card-text">
                {highlighted_param}
                </p>
        '''
        if hasattr(entry, 'use_list_variable'):
            html += f'''
                    <p>
                    <b>List Mode:</b> {entry.use_list_variable}<br>
                    <b>Variable Name:</b> {entry.list_variable_name}
                    </p>
            '''
        html += f'''
              </div>
            </div>
            '''

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
                        'form_widget_args': {
                            'param' : {"rows": 10},
                        },
                        'form_overrides' : {
                            #'param': StringField,
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)

    def on_model_change(self, form, model, is_created):
        """
        Sort Fields        
        """

        return super().on_model_change(form, model, is_created)

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
            'render_netbox_dataflow': _render_dataflow_outcome,
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

    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    def get_export_name(self, export_type):
        """
        Overwrite Filename
        """
        now = datetime.now()

        dt_str = now.strftime("%Y%m%d%H%M")
        return f"{self.model.__name__}_{dt_str}.syncer_json"
