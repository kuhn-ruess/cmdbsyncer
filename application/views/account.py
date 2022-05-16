"""
Account Model View
"""
from flask_login import current_user
from application.views.default import DefaultModelView
from markupsafe import Markup


def _render_custom_data(_view, _context, model, name):
    html = "<table>"
    for entry in model.custom_fields:
        html += f"<tr><td>{entry.name}</td><td>{entry.value}</td></tr>"
    html += "</table>"
    return Markup(html)

class AccountModelView(DefaultModelView):
    """
    Account Model
    """
    column_filters = (
       'name',
       'enabled',
    )


    column_labels = {
        'password': 'Attributes',
    }

    column_formatters = {
        'password': _render_custom_data,
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('account')
