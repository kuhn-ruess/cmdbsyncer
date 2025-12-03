"""
i-doit rule views
"""
from flask_login import current_user
from markupsafe import Markup
from wtforms import HiddenField, StringField

from application.modules.rule.views import RuleModelView
from .models import idoit_outcome_types

def _render_idoit_outcome(_view, _context, model, _name):
    """
    Render i-doit outcome
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
    Custom rule model view
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
            'render_idoit_outcome': "i-doit actions",
        })

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('i-doit')