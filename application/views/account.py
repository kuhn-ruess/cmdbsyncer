"""
Account Model View
"""
# pylint: disable=fixme
from flask import request, url_for
from markupsafe import Markup, escape
from mongoengine.errors import OperationError
from flask_login import current_user
from flask_admin.base import expose
from flask_admin.form import rules
from wtforms import StringField
from wtforms.validators import ValidationError
from application.models.cron import CronGroup
from application.views.default import DefaultModelView, name_and_enabled_filters
from application.views._form_sections import modern_form, section
from application.models.account import CustomEntry, Account
from application.helpers.plugins import discover_plugins
from application.plugins.checkmk.models import CheckmkObjectCache  # TODO: Make Plugin Compatible
from application.docu_links import docu_links

_DOCS_BADGE = rules.HTML(
    f'<a href="{docu_links["accounts"]}" target="_blank" '
    f'class="badge badge-light" style="margin-bottom: 8px;">'
    f'<i class="fa fa-info-circle"></i> Documentation</a>'
)

def _render_custom_data(_view, _context, model, _name):
    """
    Render for detail table
    """
    html = '<table class="cmdb-inline-kv">'
    for entry in model.custom_fields:
        max_len = 80
        value = entry.value[:max_len]
        if len(entry.value) > max_len:
            value += "..."
        html += f"<tr><td>{escape(entry.name)}</td><td>{escape(value)}</td></tr>"
    html += "</table>"
    return Markup(html)

def _render_plugin_data(_view, _context, model, _name):
    """
    Render for Plugin Settings
    """
    html = '<table class="cmdb-inline-kv">'
    for entry in model.plugin_settings:
        max_len = 80
        value = entry.object_filter[:max_len]
        if len(entry.object_filter) > max_len:
            value += "..."
        html += f"<tr><td>{escape(entry.plugin)}</td><td>{escape(value)}</td></tr>"
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

    column_filters = name_and_enabled_filters()

    form_rules = [
        _DOCS_BADGE,
        *modern_form(
            section('1', 'main', 'Basics',
                    'Name, parent account and activation.',
                    [rules.Field('name'),
                     rules.Field('parent'),
                     rules.Field('enabled')]),
            section('2', 'cond', 'Object Settings',
                    'Which object types this child account covers.',
                    [rules.Field('is_object'),
                     rules.Field('object_type')]),
            section('3', 'out', 'Additional Configuration',
                    'Freeform custom fields and per-plugin settings.',
                    [rules.Field('custom_fields'),
                     rules.Field('plugin_settings')]),
        ),
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

    column_filters = name_and_enabled_filters()

    column_exclude_list = ['custom_fields', 'is_child', 'parent', 'password_crypted']

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
        _DOCS_BADGE,
        *modern_form(
            section('1', 'main', 'Basics',
                    'Name, plugin type and activation.',
                    [rules.Field('name'),
                     rules.Field('type'),
                     rules.Field('is_master'),
                     rules.Field('enabled')]),
            section('2', 'cond', 'Access',
                    'How the syncer connects to this system.',
                    [rules.Field('address'),
                     rules.Field('username'),
                     rules.Field('password')]),
            section('3', 'out', 'Additional Configuration',
                    'Freeform custom fields and per-plugin overrides.',
                    [rules.Field('custom_fields'),
                     rules.Field('plugin_settings')]),
            section('4', 'aux', 'Object Settings',
                    'Which object types this account produces or targets.',
                    [rules.Field('is_object'),
                     rules.Field('cmdb_object'),
                     rules.Field('object_type')]),
        ),
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

    @expose('/new/', methods=('GET', 'POST'))
    def create_view(self):
        """
        Two-step create flow — pick the plugin type first so the custom
        fields can be pre-seeded from the plugin's
        `account_custom_field_presets` before the user starts typing.
        Skipped on POST (the main create form posts back to this same
        URL) and when `?type=...` is already in the query string.
        """
        if request.method == 'GET' and not request.args.get('type'):
            # pylint: disable=import-outside-toplevel
            from application.models.account import get_account_types
            types = sorted(
                (t for t in get_account_types() if isinstance(t, tuple)),
                key=lambda t: (t[1] or t[0]).lower(),
            )
            # self.render() wires in Flask-Admin's template context
            # (admin_base_template, admin_view, admin_static). Plain
            # render_template() would crash because admin/master.html
            # extends `admin_base_template`, which is only defined in
            # the admin context.
            return self.render(
                'admin/account_pick_type.html',
                types=types,
                next_url=url_for('.create_view'),
            )
        return super().create_view()

    @staticmethod
    def _lock_type_field(form):
        """Render the `type` dropdown read-only and freeze its value.

        Flask-Admin's Select2 widget respects `disabled` via
        ``render_kw``, but a disabled ``<select>`` isn't submitted by
        the browser — so pre-mark the field's ``process_formdata`` to
        keep the current in-memory value even if the template ignores
        the attribute. We also set ``readonly`` for Bootstrap plain
        selects and narrow the choices to the current value so a
        tampered POST can't slip another type through.
        """
        field = form.type
        current = field.data
        widget_kw = dict(getattr(field, 'render_kw', None) or {})
        widget_kw['disabled'] = True
        widget_kw['readonly'] = True
        field.render_kw = widget_kw
        if current:
            label = dict(field.choices or []).get(current, current)
            field.choices = [(current, label)]

    def edit_form(self, obj=None):
        """Lock the plugin type on edit.

        Changing the type after creation would invalidate the preset-based
        custom fields the user already set (each plugin brings its own
        schema of `account_custom_field_presets`) and has no safe-to-apply
        semantics at the plugin layer.
        """
        form = super().edit_form(obj)
        if hasattr(form, 'type'):
            self._lock_type_field(form)
        return form

    def create_form(self, obj=None):
        """Pre-fill the account form based on the plugin type from the URL.

        `on_model_change` already merges the same preset data at save
        time, but seeding the form here means the user sees the
        defaults immediately — they can tweak or delete rows before
        ever hitting Save. The picker in step 1 already captured the
        plugin type, so the dropdown stays read-only here too.
        """
        form = super().create_form(obj)

        account_type = (request.args.get('type') or '').strip()
        if not account_type:
            return form

        # Default the `type` field to the picked plugin.
        if hasattr(form, 'type') and not form.type.data:
            form.type.data = account_type
        if hasattr(form, 'type'):
            self._lock_type_field(form)

        plugins = discover_plugins() or {}
        plugin_data = plugins.get(account_type) or {}

        # Copy main_presets (address/username/…) onto the form so the
        # inputs show the defaults.
        for field, content in (plugin_data.get('account_presets') or {}).items():
            if hasattr(form, field):
                field_obj = getattr(form, field)
                if not field_obj.data:
                    field_obj.data = content

        # Seed custom_fields from the plugin's preset dict. Skip keys
        # the user already added manually (e.g. on validation redraw).
        presets = plugin_data.get('account_custom_field_presets') or {}
        if presets and hasattr(form, 'custom_fields'):
            existing = {
                str(getattr(entry.form, 'name', None).data or '').strip()
                for entry in form.custom_fields.entries
                if getattr(entry.form, 'name', None)
            }
            for key, value in presets.items():
                if key in existing:
                    continue
                form.custom_fields.append_entry(
                    {'name': key, 'value': value}
                )

        return form

    def on_model_change(self, form, model, is_created):
        """
        Create Defauls for Account on create
        """
        # The edit form ships `type` as disabled, so the browser doesn't
        # submit it — form.type.data is empty on edit. Fall back to what
        # is already on the model so the preset lookup (and every field
        # below) targets the original plugin type.
        account_type = form.type.data or model.type
        main_presets = []
        default_fields = []
        plugins = discover_plugins()
        if plugin_data := plugins.get(account_type):
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
