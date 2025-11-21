"""
Account Model View
"""
from markupsafe import Markup
from mongoengine.errors import OperationError
from flask_login import current_user
from flask_admin.form import rules
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike
from wtforms import StringField
from wtforms.validators import ValidationError
from application.models.cron import CronGroup
from application.views.default import DefaultModelView
from application.models.account import CustomEntry, Account
from application.helpers.plugins import discover_plugins
from application.plugins.checkmk.models import CheckmkObjectCache # TODO: Make Plugin Compatible
from application.docu_links import docu_links
from mongoengine.queryset.visitor import Q

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

class ChildAccountModelView(DefaultModelView):
    """
    Child Account Model
    """

    def get_query(self):
        """
        Limit Objects
        """
        return Account.objects(is_child=True).order_by('name')

    column_exclude_list = [
            'custom_fields', 'is_child', 'type',
            'is_master', 'address', 'username', 'password']

    column_filters = (
       FilterLike(
            "name",
           'Name'
       ),
       BooleanEqualFilter(
            "enabled",
           'Enabled'
       )
    )

    form_rules = [
        rules.HTML(f'<i class="fa fa-info"></i><a href="{docu_links["accounts"]}"'\
                        'target="_blank" class="badge badge-light">Documentation</a>'),
        rules.FieldSet(('name', 'parent'),'Settings'),
        rules.FieldSet(('is_object', 'object_type'), "Object Settings"),
        rules.Header("Addional configuration"),
        rules.Field('custom_fields'),
        rules.Field('plugin_settings'),
        rules.Field('enabled'),
    ]


    def on_model_change(self, form, model, is_created):
        """
        On Save Operations
        """
        model.is_child = True
        return super().on_model_change(form, model, is_created)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('account')

class AccountModelView(DefaultModelView):
    """
    Account Model
    """

    def get_query(self):
        """
        Limit Objects
        """
        return Account.objects(is_child__ne=True).order_by('name', 'typ')

    column_filters = (
       FilterLike(
            "name",
           'Name'
       ),
       BooleanEqualFilter(
            "enabled",
           'Enabled'
       )
    )

    column_exclude_list = ['custom_fields', 'is_child', 'parent', 'password_crypted']

    column_formatters = {
        'plugin_settings': _render_plugin_data,
    }

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
        rules.FieldSet(('name', 'type'),'Basics'),
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
        plugins = discover_plugins()
        if plugin_data := plugins.get(form.type.data):
            main_presets = plugin_data.get('account_presets', {}).items()
            default_fields = plugin_data.get('account_custom_field_presets', {}).items()

        for field in model.custom_fields:
            field.value = field.value.strip()

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

        if form.password.data:
            model.set_password(form.password.data)
            model.password = ""
        return super().on_model_change(form, model, is_created)

    def on_model_delete(self, model):
        """
        Prevent deletion of Accounts with Assigned References
        """
        # Problem: Reverse Delete Rules not woking for EmbeddedDocument
        for group in CronGroup.objects():
            for job in group.jobs:
                if job.account == model:
                    raise ValidationError(f"Can't delete: Used by Cronjob '{group.name}'")

        for entry in CheckmkObjectCache.objects():
            if entry.account == model:
                raise ValidationError("Can't delete: Cache objectes have this Account Assigned")

        try:
            model.delete()
        except OperationError as error:
            raise \
               ValidationError("Can't delete: Other Objects  have this Account Assigned") from error


    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('account')
