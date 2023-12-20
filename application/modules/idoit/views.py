"""
Idoit Rule Views
"""
from markupsafe import Markup
from wtforms import HiddenField, StringField

from application.modules.rule.views import RuleModelView
from application.modules.idoit.models import idoit_outcome_types

def _render_idoit_outcome(_view, _context, model, _name):
    """
    Render Netbox outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{dict(idoit_outcome_types)[entry.action]}</td>"
        if entry.param:
            html += f"<td><b>{entry.param}</b></td></tr>"
    html += "</table>"
    return Markup(html)


#pylint: disable=too-few-public-methods
class IdoitCustomAttributesView(RuleModelView):
    """
    Custom Rule Model View
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        self.column_formatters.update({
            'render_idoit_outcome': _render_idoit_outcome,
        })

        self.form_overrides.update({
            'render_idoit_outcome': HiddenField,
        })

        self.column_labels.update({
            'render_idoit_outcome': "Idoit Actions",
        })

        #pylint: disable=access-member-before-definition
        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments' : {
                    '': {
                        'form_overrides' : {
                            'param': StringField,
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)
