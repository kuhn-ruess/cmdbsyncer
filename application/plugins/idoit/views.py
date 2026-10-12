"""
i-doit rule views
"""
from flask_login import current_user
from markupsafe import Markup, escape
from wtforms import HiddenField

from application.modules.rule.views import RuleModelView
from application.modules.rule.list_source_views import ListSourceViewMixin
from .models import idoit_outcome_types

def _render_idoit_outcome(_view, _context, model, _name):
    """
    Render i-doit outcome
    """

    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{escape(dict(idoit_outcome_types)[entry.action])}</td>"
        if entry.param:
            html += f"<td><b>{escape(entry.param)}</b></td></tr>"
    html += "</table>"
    return Markup(html)


class IdoitCustomAttributesView(ListSourceViewMixin, RuleModelView):  # pylint: disable=too-many-ancestors
    """
    Custom rule model view
    """
    list_source_creates = 'i-doit object'
    list_source_help_items = (
        'The column <code>hostname</code> (or <code>name</code>) is the '
        'title of the object, a row without it creates none.',
    )
    list_source_outcome = ('i-doit Actions',
                           'Object type, description and categories of the object.')
    list_source_template_fields = (('param', 'Parameter'),)

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
