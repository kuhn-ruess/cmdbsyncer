"""
Account Model View
"""
from markupsafe import Markup
from flask_login import current_user
from wtforms import StringField
from application.views.default import DefaultModelView


def _render_custom_data(_view, _context, model, _name):
    """
    Render for detail table
    """
    html = "<table width=100%>"
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

    form_overrides = {
        'name': StringField,
        'password': StringField,
        'address': StringField,
        'username': StringField,
    }

    form_widget_args = {
        'password': {'autocomplete': 'new-password' },
    }


    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('account')
