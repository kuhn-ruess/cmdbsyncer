"""
Account Model View
"""
from markupsafe import Markup
from flask_login import current_user
from wtforms import StringField
from wtforms.validators import ValidationError
from application.models.cron import CronGroup
from application.views.default import DefaultModelView
from application.models.account import CustomEntry
from application.modules.checkmk.models import CheckmkObjectCache

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
                ('rewrite_hostname', None),
            ]
        elif form.typ.data == 'json':
            default_fields = [
                ('path', ''),
                ('hostname_field', 'host'),
                ('rewrite_hostname', None),
            ]
        elif form.typ.data == 'maintenance':
            default_fields = [
                ('delete_hosts_after_days', '0'),
                ('account_filter', None),
            ]
        elif form.typ.data == 'mysql':
            default_fields = [
                ('hostname_field', ''),
                ('rewrite_hostname', None),
            ]
        elif form.typ.data == 'external_restapi':
            default_fields = [
                ('auth_type', "Basic"),
                ('request_headers', '{"Content-Type": "application/json"}'),
                ('data_key', 'result'),
                ('hostname_field', 'host'),
                ('rewrite_hostname', None),
            ]
        elif form.typ.data == 'cmkv2':
            default_fields = [
                ('account_filter', ""),
            ]
        elif form.typ.data == 'ldap':
            default_fields = [
                ('base_dn', ""),
                ('search_filter', ""),
                ('attributes', "memberOf"),
                ('hostname_field', 'host'),
                ('encoding', 'ascii'),
                ('rewrite_hostname', None),
            ]
        elif form.typ.data == 'mssql':
            default_fields = [
                ('fields', ""),
                ('table', ""),
                ('instance', ""),
                ('database', ""),
                ('where', None),
                ('hostname_field', 'host'),
                ('rewrite_hostname', None),
                ('driver', "ODBC Driver 18 for SQL Server"),
            ]


        if default_fields:
            for field, content in default_fields:
                if field not in [x.name for x in model.custom_fields]:
                    new = CustomEntry()
                    new.name = field
                    new.value = content
                    model.custom_fields.append(new)

        return super().on_model_change(form, model, is_created)

    def on_model_delete(self, model):
        """
        Prevent deletion of Accounts with Assigned References
        """
        for group in CronGroup.objects():
            for job in group.jobs:
                if job.account == model:
                    raise ValidationError(f"Can't delete: Used by Cronjob '{group.name}'")

        for entry in CheckmkObjectCache.objects():
            if entry.account == model:
                raise ValidationError("Can't delete: Cache objectes have this Account Assigned")


    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('account')
