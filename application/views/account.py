"""
Account Model View
"""
from markupsafe import Markup
from flask_login import current_user
from wtforms import StringField
from application.views.default import DefaultModelView
from application.models.account import CustomEntry


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


    def on_model_change(self, form, model, is_created):
        """
        Create Defauls for Account on create
        """
        default_fields = []
        if form.typ.data == 'csv':
            default_fields = [
                ('path', ''),
                ('hostname_field', 'host'),
                ('delimiter', ';'),
                ('encoding', 'utf-8'),
            ]
        elif form.typ.data == 'json':
            default_fields = [
                ('path', ''),
                ('hostname_field', 'host'),
            ]
        elif form.typ.data == 'maintenance':
            default_fields = [
                ('delete_hosts_after_days', '0'),
                ('account_filter', None),
            ]
        elif form.typ.data == 'external_restapi':
            default_fields = [
                ('auth_type', "Basic"),
                ('request_headers', '{"Content-Type": "application/json"}'),
                ('data_key', 'result'),
                ('hostname_field', 'host'),
            ]


        if default_fields:
            for field, content in default_fields:
                if field not in [x.name for x in model.custom_fields]:
                    new = CustomEntry()
                    new.name = field
                    new.value = content
                    model.custom_fields.append(new)

        return super().on_model_change(form, model, is_created)


    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('account')
