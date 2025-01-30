"""
Account Model View
"""
from markupsafe import Markup
from flask_login import current_user
from wtforms import StringField
from flask_admin.form import rules
from wtforms.validators import ValidationError
from application.models.cron import CronGroup
from application.views.default import DefaultModelView
from application.models.account import CustomEntry
from application.modules.checkmk.models import CheckmkObjectCache
from application.docu_links import docu_links

def _render_custom_data(_view, _context, model, _name):
    """
    Render for detail table
    """
    html = "<table width=100%>"
    for entry in model.custom_fields:
        max_len = 80
        value = entry.value[:max_len]
        if len(entry.value) > max_len:
            value += "..."
        html += f"<tr><td>{entry.name}</td><td>{value}</td></tr>"
    html += "</table>"
    return Markup(html)

def _render_plugin_data(_view, _context, model, _name):
    """
    Render for Plugin Settings
    """
    html = "<table width=100%>"
    for entry in model.plugin_settings:
        max_len = 80
        value = entry.object_filter[:max_len]
        if len(entry.object_filter) > max_len:
            value += "..."
        html += f"<tr><td>{entry.plugin}</td><td>{value}</td></tr>"
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

    column_exclude_list = ['custom_fields', ]

    form_subdocuments = {
        'custom_fields': {
            'form_subdocuments' : {
                '': {
                'form_widget_args': {
                    'name': { 'style': 'background-color: #81DAF5;'},
                    'value': { 'style': 'background-color: #81DAF5;'},
                },
                    'form_overrides' : {
                        'name': StringField,
                    },
                    'form_rules' : [
                        rules.HTML("<div class='form-row'><div class='col-3'>"),
                        rules.Field('name'),
                        rules.HTML("</div><div class='col-9'>"),
                        rules.Field('value'),
                        rules.HTML("</div></div>"),
                    ]
                },
            },
        }
    }


    form_rules = [
        rules.HTML(f'<i class="fa fa-info"></i><a href="{docu_links["accounts"]}"'\
                        'target="_blank" class="badge badge-light">Documentation</a>'),
        rules.FieldSet(('name', 'typ'),'Basics'),
        rules.FieldSet(('is_master',), "Account Settings"),
        rules.FieldSet(('is_object', 'object_type'), "Object Settings"),
        rules.FieldSet(('address', 'username', 'password'), "Access Config"),
        rules.Header("Addional configuration"),
        rules.Field('custom_fields'),
        rules.Field('plugin_settings'),
        rules.Field('enabled'),
    ]



    column_labels = {
        'password': 'Attributes',
    }

    column_formatters = {
        'password': _render_custom_data,
        'plugin_settings': _render_plugin_data,
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
        main_presets = []
        default_fields = []
        if form.typ.data == 'csv':
            default_fields = [
                ('path', ''),
                ('hostname_field', 'host'),
                ('delimiter', ';'),
                ('encoding', 'utf-8'),
                ('rewrite_hostname', ""),
                ('inventorize_key', ""),
                ('inventorize_match_by_domain', ""),
                ('inventorize_match_attribute', ""),
                ('inventorize_collect_by_key', ""),
                ('inventorize_rewrite_collect_by_key', ""),
            ]
        elif form.typ.data == 'json':
            default_fields = [
                ('path', ''),
                ('hostname_field', 'host'),
                ('rewrite_hostname', ""),
                ('data_key', ''),
            ]
        elif form.typ.data == 'maintenance':
            default_fields = [
                ('delete_hosts_after_days', '0'),
                ('account_filter', ""),
            ]
        elif form.typ.data == 'mysql':
            default_fields = [
                ('hostname_field', ''),
                ('rewrite_hostname', ""),
                ('table', ""),
                ('fields', ""),
                ('database', ""),
                ('custom_query', ""),
                ('inventorize_key', ""),
                ('inventorize_match_by_domain', ""),
                ('inventorize_match_attribute', ""),
                ('inventorize_collect_by_key', ""),
                ('inventorize_rewrite_collect_by_key', ""),
            ]
        elif form.typ.data == 'external_restapi':
            default_fields = [
                ('auth_type', "Basic"),
                ('request_headers', '{"Content-Type": "application/json"}'),
                ('data_key', 'result'),
                ('hostname_field', 'host'),
                ('rewrite_hostname', ""),
            ]
        elif form.typ.data == 'cmkv2':
            default_fields = [
                ('limit_by_accounts', ""),
                ('limit_by_hostnames', ""),
                ('list_disabled_hosts', ""),
            ]
        elif form.typ.data == 'ldap':
            default_fields = [
                ('base_dn', ""),
                ('search_filter', ""),
                ('attributes', "memberOf"),
                ('hostname_field', 'host'),
                ('encoding', 'ascii'),
                ('rewrite_hostname', ""),
                ('inventorize_key', ""),
                ('inventorize_match_by_domain', ""),
                ('inventorize_match_attribute', ""),
                ('inventorize_collect_by_key', ""),
                ('inventorize_rewrite_collect_by_key', ""),
            ]
        elif form.typ.data == 'mssql':
            default_fields = [
                ('fields', ""),
                ('table', ""),
                ('instance', ""),
                ('serverport', ""),
                ('database', ""),
                ('custom_query', ""),
                ('hostname_field', 'host'),
                ('rewrite_hostname', ""),
                ('driver', "ODBC Driver 18 for SQL Server"),
                ('inventorize_key', ""),
                ('inventorize_match_by_domain', ""),
                ('inventorize_match_attribute', ""),
                ('inventorize_collect_by_key', ""),
                ('inventorize_rewrite_collect_by_key', ""),
            ]
        elif form.typ.data == 'odbc':
            default_fields = [
                ('fields', ""),
                ('table', ""),
                ('instance', ""),
                ('serverport', ""),
                ('database', ""),
                ('custom_query', ""),
                ('hostname_field', 'host'),
                ('rewrite_hostname', ""),
                ('driver', "FreeTDS"),
                ('inventorize_key', ""),
                ('inventorize_match_by_domain', ""),
                ('inventorize_match_attribute', ""),
                ('inventorize_collect_by_key', ""),
                ('inventorize_rewrite_collect_by_key', ""),
            ]
        elif form.typ.data == 'bmc_remedy':
            default_fields = [
                #('attributes', "address,systemname,dnshostname"),
                ('hostname_field', 'dnshostname'),
                ('namespace', ""),
                ('class_name', ""),
            ]
        elif form.typ.data == 'jira':
            default_fields = [
                ('page_size', "1000"),
            ]

        elif form.typ.data == 'i-doit':
            default_fields = [
                ('api_token', ""),
            ]
        elif form.typ.data == 'netbox':
            default_fields = [
                ('rewrite_hostname', ""),
                ('verify_cert', "True"),
                ('import_filter', ""),

            ]
        elif form.typ.data == 'jdisc':
            main_presets = [
                ('address', 'https://SERVER/graphql'),
            ]
            default_fields = [
                ('rewrite_hostname', ""),
                ('import_unnamed_devices', ""),
            ]

        if default_fields:
            for field, content in default_fields:
                if field not in [x.name for x in model.custom_fields]:
                    new = CustomEntry()
                    new.name = field
                    new.value = content
                    model.custom_fields.append(new)
        if main_presets:
            for field, content in main_presets:
                if not getattr(model, field):
                    setattr(model, field, content)

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
