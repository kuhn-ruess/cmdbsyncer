"""
Account Model View
"""
# pylint: disable=fixme
import re

from flask import flash, g, redirect, request, url_for
from markupsafe import Markup, escape
from mongoengine.errors import OperationError
from mongoengine.errors import ValidationError as ModelValidationError
from flask_login import current_user
from flask_admin.actions import action
from flask_admin.base import expose
from flask_admin.form import rules
from flask_admin.model.fields import InlineFieldList
from wtforms import SelectField, StringField
from wtforms.validators import Optional, ValidationError
from application import plugin_register
from application.models.cron import CronGroup, job_account, job_account_id
from application.views.default import DefaultModelView, name_and_enabled_filters
from application.views._form_sections import modern_form, section
from application.models.account import (CustomEntry, Account, account_restrictions,
                                        object_types)
from application.models.host import Host
from application.models.host_templates import assignable_templates
from application.helpers.get_account import get_account_by_name
from application.helpers.import_hostnames import take_over_shadow_data
from application.helpers.plugins import custom_field_help, discover_plugins, plugin_jobs
from application.helpers.account_jobs import (FORBIDDEN_KINDS, account_job_settings,
                                              job_kind, job_problems,
                                              several_imports)
from application.plugins.checkmk.models import CheckmkObjectCache  # TODO: Make Plugin Compatible
from application.docu_links import docu_links

_DOCS_BADGE = rules.HTML(
    f'<a href="{docu_links["accounts"]}" target="_blank" '
    f'class="badge badge-light" style="margin-bottom: 8px;">'
    f'<i class="fa fa-info-circle"></i> Documentation</a>'
)


# Shared switch explanations — user-facing wording, kept identical between the
# main and child account forms where the same switch appears.
_HELP_IS_MASTER = "Takes over hosts another account imported first."
_HELP_SHADOW_MODE = "Only stores labels next to the current ones, to compare."
_HELP_IS_OBJECT = (
    "Objects (locations, contracts, ...) are never exported as hosts. The "
    "account decides this, not the job name."
)
_IMPORTS_AS_CHOICES = [('', 'Hosts'), ('1', 'Objects')]
_HELP_RESTRICT_TO = (
    "Limits the jobs the account may run. An additional source writes under "
    "its inventory key."
)
_HELP_INVENTORY_KEY = (
    "The inventory of the hosts gets the data under this prefix, e.g. snow. "
    "Saved as custom field inventorize_key."
)
_HELP_ACCOUNT_JOBS = (
    "Run Jobs defined by Account runs them in this order. None: the import, "
    "for an additional source the inventorize. Several import jobs, devices "
    "and VMs for example, make the object type Automatic."
)
_HELP_VALID_HOSTNAME = "Skips names that are no valid hostname (object type Host Object)."
_HELP_REQUIRE_FQDN = "Skips names that are no FQDN."

# The roles explained in the choice itself, the model keeps the short names
_ROLE_CHOICES = [
    ('', "Not limited: every job allowed"),
    ('import', "Main source: imports hosts and their labels"),
    ('inventorize', "Additional source: adds inventory to hosts of other accounts"),
    ('export', "Export target: only exports, no import or inventorize"),
]

_SOURCE_SECTION_DESC = 'What the account delivers and how it treats hosts of others.'

_HELP_AUTO_APPLY_TEMPLATES = "CMDB templates every imported entry gets."


def _template_choices(form):
    """
    Offer only CMDB templates in the Auto Apply Templates picker. Set per
    form, since a queryset kept on the form class caches its first result.
    """
    if hasattr(form, 'auto_apply_templates'):
        form.auto_apply_templates.queryset = assignable_templates()
    return form


def _source_choices(form):
    """Explain the roles and what an import creates in the choices"""
    if hasattr(form, 'restrict_to'):
        form.restrict_to.choices = _ROLE_CHOICES
    if hasattr(form, 'is_object'):
        form.is_object.choices = _IMPORTS_AS_CHOICES
    return form


def _check_jobs(model, account_type):
    """
    Refuse jobs of other plugins or jobs the role does not allow, in
    Jobs and in Plugin Settings. Several import jobs make the object
    type Automatic.
    """
    settings = account_job_settings(model)
    settings['typ'] = account_type
    if problems := job_problems(settings):
        raise ValidationError(problems[0])
    if several_imports(settings['account_jobs']):
        # Each import job decides what it creates, devices and VMs alike
        model.object_type = 'auto'
    allowed = plugin_jobs(account_type)
    for entry in model.plugin_settings:
        if entry.plugin not in allowed:
            raise ValidationError(f"Plugin Settings: {entry.plugin} is no job of "
                                  f"accounts of type {account_type}")


class _SourceViewMixin:  # pylint: disable=too-few-public-methods
    """What account_source_fields.html needs to offer only fitting jobs"""

    forbidden_kinds = {role: sorted(kinds) for role, kinds in FORBIDDEN_KINDS.items()}

    @staticmethod
    def plugin_jobs_by_type():
        """The jobs Plugin Settings offers, by account type"""
        return {account_type: plugin_jobs(account_type)
                for account_type in discover_plugins()}

    @staticmethod
    def job_kinds():
        """Import, inventorize or other, by job name, for the role filter"""
        return {job: job_kind(job) for job in plugin_register}

    @staticmethod
    def parent_types():
        """Type of every main account, a child account has the one of its parent"""
        return {str(account.id): account.type
                for account in Account.objects(is_child__ne=True).only('type')}

    def scaffold_form(self):
        """The inventory key of an additional source, kept in custom_fields"""
        form_class = super().scaffold_form()
        form_class.inventory_key = StringField('Inventory key', validators=[Optional()])
        return form_class


def _show_inventory_key(form, obj):
    """The inventorize_key custom field of the account in its own field"""
    if request.method != 'GET' or obj is None or not hasattr(form, 'inventory_key'):
        return form
    for entry in obj.custom_fields:
        if entry.name == 'inventorize_key':
            form.inventory_key.data = entry.value
    return form


def _store_inventory_key(form, model):
    """Write the Inventory key field into the custom field inventorize_key"""
    value = (getattr(form, 'inventory_key', None) and form.inventory_key.data or '').strip()
    if not value:
        return
    for entry in model.custom_fields:
        if entry.name == 'inventorize_key':
            entry.value = value
            return
    model.custom_fields.append(CustomEntry(name='inventorize_key', value=value))


_HELP_CMDB_OBJECT = "Gets the CMDB template and default fields, stays when gone from the source."


# Layout of the Source section: pairs of fields side by side, the
# switches as compact rows, the rarely used import settings folded away.
# Colors only from theme variables, so all themes render it.
_SOURCE_CSS = rules.HTML(
    '<style>'
    '.acct-row{display:grid;grid-template-columns:1fr 1fr;gap:0 16px;}'
    '.acct-row>.acct-cell:only-child{grid-column:1/-1;}'
    '@media (max-width:700px){.acct-row{grid-template-columns:1fr;}}'
    '.acct-check .form-group{display:flex;flex-direction:row-reverse;'
    'justify-content:flex-end;align-items:center;gap:8px;margin-bottom:0;}'
    '.acct-check .form-group label{margin:0;padding:0;}'
    '.acct-hint{margin:2px 0 12px;font-size:0.82rem;'
    'color:var(--surface-muted,#6c757d);}'
    '.acct-more{margin:4px 0 8px;}'
    '.acct-more>summary{cursor:pointer;color:var(--surface-muted,#6c757d);'
    'margin-bottom:8px;}'
    # One line per job: drag handle (the legend), select, remove button
    '#account_jobs .inline-field.card{display:flex;flex-direction:row;'
    'align-items:center;gap:4px;padding:4px 40px 4px 8px;'
    'margin-bottom:6px!important;}'
    '#account_jobs .inline-field.card>legend{width:auto;margin:0;}'
    '#account_jobs .inline-field.card>legend small{font-size:0;}'
    '#account_jobs .inline-field.card>select{flex:1 1 auto;}'
    '#account_jobs .inline-field.card>.clearfix{display:none;}'
    '#account_jobs .cmdb-inline-remove{top:50%;transform:translateY(-50%);}'
    '</style>'
)


def _hint(text):
    """A short help line for a field of the Source section"""
    return rules.HTML(f'<p class="acct-hint">{escape(text)}</p>')


def _cell(*field_rules, cell_id=None):
    """One grid cell of an .acct-row"""
    attribute = f' id="{cell_id}"' if cell_id else ''
    return [rules.HTML(f'<div class="acct-cell"{attribute}>'), *field_rules,
            rules.HTML('</div>')]


def _row(*cells):
    """Fields side by side"""
    return [rules.HTML('<div class="acct-row">'),
            *[rule for cell in cells for rule in cell],
            rules.HTML('</div>')]


def _check(field, text):
    """A switch with its label on the right and a short help below"""
    return [rules.HTML('<div class="acct-cell acct-check">'),
            rules.Field(field), _hint(text), rules.HTML('</div>')]


def _import_fields(*field_rules):
    """
    The fields which only matter for an account that creates entries,
    hidden by account_source_fields.html for the other roles
    """
    return [rules.HTML('<div id="account-import-fields">'),
            *field_rules,
            rules.HTML('</div>')]


def _more_settings(*field_rules):
    """Import settings most accounts leave alone, folded away"""
    return [rules.HTML('<details class="acct-more"><summary>More import '
                       'settings</summary>'),
            *field_rules,
            rules.HTML('</details>')]


_ROLE_RULES = [
    _SOURCE_CSS,
    *_row(_cell(rules.Field('restrict_to'), _hint(_HELP_RESTRICT_TO),
                rules.HTML('<div id="account-inventory-key">'),
                rules.Field('inventory_key'), _hint(_HELP_INVENTORY_KEY),
                rules.HTML('</div>')),
          _cell(rules.Field('account_jobs'), _hint(_HELP_ACCOUNT_JOBS))),
]
_IMPORTS_AS_RULES = [
    *_row(_cell(rules.Field('is_object'), _hint(_HELP_IS_OBJECT)),
          _cell(rules.Field('object_type'), cell_id='account-object-type')),
]
_TEMPLATE_AND_NAME_RULES = [
    rules.Field('auto_apply_templates'),
    _hint(_HELP_AUTO_APPLY_TEMPLATES),
    *_row(_check('check_for_valid_hostname', _HELP_VALID_HOSTNAME),
          _check('require_fqdn', _HELP_REQUIRE_FQDN)),
]

class _JobListField(InlineFieldList):
    """
    The jobs of an account in their order, one select per row. A multi
    select would lose the order. The rows offer every job, the form
    script leaves those of the plugin, saving checks them.
    """

    def __init__(self, **kwargs):
        super().__init__(
            SelectField(choices=lambda: [(job, job) for job in plugin_register],
                        validate_choice=False,
                        render_kw={'class': 'form-control form-control-sm'}),
            min_entries=0, **kwargs)


class _PasswordField(StringField):
    """
    The account password, put on the account encrypted as it is read
    from the form.

    Doing it while the form fills the account, instead of afterwards in
    on_model_change, means every way of saving the form gets it. The
    approval workflow fills a copy of the account and stores that for
    later, without on_model_change: the typed password used to land in
    the plain text field there, and on approval the account kept its
    old encrypted one, so the new password never took effect.
    """

    def populate_obj(self, obj, name):
        if self.data:
            obj.encrypt_password(self.data)
        # Only legacy accounts have a plain text password, and the form
        # shows it to them, so it comes back here and gets encrypted.
        setattr(obj, name, "")


# Custom fields the account list shows before folding the rest away
_LIST_FIELDS_SHOWN = 4


def _kv_table(pairs):
    """Key/value pairs as the small table of a list cell, long values cut"""
    max_len = 80
    html = '<table class="cmdb-inline-kv">'
    for key, value in pairs:
        value = value or ''
        short = value[:max_len] + ("..." if len(value) > max_len else "")
        html += f"<tr><td>{escape(key)}</td><td>{escape(short)}</td></tr>"
    return html + "</table>"


def _render_custom_data(_view, _context, model, _name):
    """
    Render for the list: only the fields with a value — a plugin seeds up
    to 20 presets, most of them left empty — and of those only the first
    few, the rest folded away so one account does not fill the screen
    """
    pairs = [(x.name, x.value) for x in model.custom_fields if x.value]
    html = _kv_table(pairs[:_LIST_FIELDS_SHOWN])
    if rest := pairs[_LIST_FIELDS_SHOWN:]:
        html += (f'<details class="cmdb-inline-more"><summary>+{len(rest)} more'
                 f'</summary>{_kv_table(rest)}</details>')
    return Markup(html)

def _render_plugin_data(_view, _context, model, _name):
    """
    Render for Plugin Settings
    """
    return Markup(_kv_table((x.plugin, ', '.join(x.object_filter or []))
                            for x in model.plugin_settings))

def _render_type(_view, _context, model, _name):
    """
    Render the type as before, tagged with its label for the group
    headings of the account list
    """
    # pylint: disable-next=no-member,protected-access
    labels = dict(Account._fields['type'].choices or [])
    value = model.type or ''
    return Markup(f'<span class="account-type" data-type="{escape(value)}" '
                  f'data-id="{model.id}" '
                  f'data-label="{escape(labels.get(value, value))}">{escape(value)}</span>')


def accounts_in_cron():
    """Ids of the accounts a cron job names, once per request"""
    if 'accounts_in_cron' not in g:
        g.accounts_in_cron = {job_account_id(job)
                              for group in CronGroup.objects().only('jobs')
                              for job in group.jobs}
    return g.accounts_in_cron


def without_cron(model):
    """An account with a role is meant to run, but no cron job runs it"""
    return bool(model.restrict_to) and str(model.id) not in accounts_in_cron()


_NO_CRON = 'In no cron job'


def _render_role(_view, _context, model, _name):
    """The role, with a warning when no cron job uses the account"""
    html = escape(dict(account_restrictions).get(model.restrict_to or '', ''))
    if without_cron(model):
        html += Markup(f' <span class="badge badge-warning">{_NO_CRON}</span>')
    return Markup(html)


def _render_options(_view, _context, model, _name):
    """
    The switches of the account in one column, only those that are set:
    one column per switch made the list wider than the window
    """
    options = []
    if model.is_master:
        options.append('Master')
    if model.shadow_mode:
        options.append('Shadow source')
    if model.is_object:
        labels = dict(object_types)
        options.append(f"Objects: {labels.get(model.object_type, model.object_type or '')}")
    if model.cmdb_object:
        options.append('CMDB object')
    if model.check_for_valid_hostname:
        options.append('Valid hostnames only')
    if model.require_fqdn:
        options.append('FQDN required')
    return Markup('<br>'.join(escape(option) for option in options))


def child_name(model):
    """
    A name for a child account saved without one: the parent and its
    first job, else its role, numbered when taken
    """
    parent = model.parent.name if model.parent else 'account'
    if model.account_jobs:
        what = model.account_jobs[0].split(':', 1)[-1]
    else:
        what = model.restrict_to or 'child'
    base = re.sub(r'[^a-z0-9_.]+', '-', f'{parent}-{what}'.lower()).strip('-')
    name, number = base, 2
    while Account.objects(name=name, id__ne=model.id).first():
        name, number = f'{base}-{number}', number + 1
    return name


def child_rows():
    """
    The child accounts by the id of their parent, for the rows the
    account list shows indented under each parent
    """
    roles = dict(account_restrictions)
    back = url_for('account.index_view')
    rows = {}
    for child in Account.objects(is_child=True).order_by('name'):
        parent = child.parent
        if not parent:
            continue
        rows.setdefault(str(parent.id), []).append({
            'name': child.name,
            'enabled': bool(child.enabled),
            'role': roles.get(child.restrict_to or '', ''),
            'jobs': list(child.account_jobs or []),
            'no_cron': without_cron(child),
            'edit': url_for('account_childs.edit_view', id=str(child.id), url=back),
        })
    return rows

class ChildAccountModelView(_SourceViewMixin, DefaultModelView):
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
            'is_master', 'address', 'username', 'password', 'auto_apply_templates']

    column_formatters = {'restrict_to': _render_role}

    column_filters = name_and_enabled_filters()

    column_labels = {
        'require_fqdn': 'Require FQDN',
        'restrict_to': 'Role',
        'account_jobs': 'Jobs',
        'auto_apply_templates': 'Auto Apply Templates',
    }

    form_args = {
        'require_fqdn': {'label': 'Require FQDN'},
        'restrict_to': {'label': 'Role'},
        'account_jobs': {'label': 'Jobs'},
        'is_object': {'label': 'Imports as', 'coerce': bool},
        'object_type': {'label': 'Object type'},
        'auto_apply_templates': {'label': 'Auto Apply Templates',
                                 'validators': [Optional()]},
    }

    form_rules = [
        _DOCS_BADGE,
        *modern_form(
            section('1', 'main', 'Basics',
                    'Name, parent account and activation.',
                    [rules.Field('name'),
                     rules.Field('parent'),
                     rules.Field('enabled')]),
            section('2', 'cond', 'Source', _SOURCE_SECTION_DESC,
                    [*_ROLE_RULES,
                     *_import_fields(*_IMPORTS_AS_RULES,
                                     *_more_settings(*_TEMPLATE_AND_NAME_RULES))]),
            section('3', 'out', 'Additional Configuration',
                    'Freeform custom fields and per-plugin settings.',
                    [rules.Field('custom_fields'),
                     rules.Field('plugin_settings')]),
        ),
    ]


    form_overrides = {
        'is_object': SelectField,
        'account_jobs': _JobListField,
    }

    edit_template = 'admin/account_child_edit.html'
    create_template = 'admin/account_child_create.html'

    def create_form(self, obj=None):
        """
        Offer only CMDB templates to apply. "Add child" of the account
        list passes the parent.
        """
        form = _source_choices(_template_choices(super().create_form(obj)))
        parent_id = request.args.get('parent')
        if parent_id and hasattr(form, 'parent') and not form.parent.data:
            form.parent.data = Account.objects(id=parent_id, is_child__ne=True).first()
        return form

    def is_visible(self):
        """The account list shows the children under their parent"""
        return False

    def scaffold_form(self):
        """The name may stay empty, saving sets it"""
        form_class = super().scaffold_form()
        form_class.name = StringField(
            'Name', validators=[Optional()],
            description='Empty: set from the parent and the first job or the role.')
        return form_class

    def edit_form(self, obj=None):
        """Offer only CMDB templates to apply"""
        return _show_inventory_key(_source_choices(_template_choices(super().edit_form(obj))),
                                   obj)

    def on_model_change(self, form, model, is_created):
        """
        On Save Operations
        """
        model.is_child = True
        _check_jobs(model, model.parent.type if model.parent else None)
        _store_inventory_key(form, model)
        if not (model.name or '').strip():
            model.name = child_name(model)
        return super().on_model_change(form, model, is_created)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('account')

class AccountModelView(_SourceViewMixin, DefaultModelView):
    """
    Account Model
    """

    def get_query(self):
        """
        Limit Objects
        """
        return Account.objects(is_child__ne=True).order_by('type', 'name')

    column_filters = name_and_enabled_filters()

    # Role and Enabled up front, the switches in one column, so the list
    # fits the window
    column_list = ['name', 'type', 'restrict_to', 'enabled', 'address', 'username',
                   'password', 'plugin_settings', 'options']

    # The custom fields are name/value pairs, so what they configure is
    # invisible in the form. These templates add the help of a field
    # under its row, read from the plugin's plugin.json.
    edit_template = 'admin/account_edit.html'
    create_template = 'admin/account_create.html'
    list_template = 'admin/account_list.html'

    @staticmethod
    def child_rows():
        """Child accounts by parent id, for the account list"""
        return child_rows()

    @staticmethod
    def add_child_url():
        """Create a child account, the list adds the parent id"""
        return url_for('account_childs.create_view', url=url_for('account.index_view'))

    @staticmethod
    def custom_field_help():
        """What every account custom field configures, by plugin type."""
        return custom_field_help()

    form_subdocuments = {
        'custom_fields': {
            'form_subdocuments' : {
                '': {
                    # One line per field: account_custom_fields.html lays
                    # the entries out as compact rows
                    'form_widget_args': {
                        'value': {'rows': 1},
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
                     rules.Field('enabled')]),
            section('2', 'cond', 'Source', _SOURCE_SECTION_DESC,
                    [*_ROLE_RULES,
                     *_import_fields(
                         *_IMPORTS_AS_RULES,
                         *_row(_check('is_master', _HELP_IS_MASTER),
                               _check('shadow_mode', _HELP_SHADOW_MODE)),
                         *_more_settings(
                             rules.HTML('<div id="account-cmdb-object">'),
                             *_check('cmdb_object', _HELP_CMDB_OBJECT),
                             rules.HTML('</div>'),
                             *_TEMPLATE_AND_NAME_RULES))]),
            section('3', 'aux', 'Access',
                    'How the syncer connects to this system.',
                    [rules.Field('address'),
                     rules.Field('username'),
                     rules.Field('password')]),
            section('4', 'out', 'Additional Configuration',
                    'Freeform custom fields and per-plugin overrides.',
                    [rules.Field('custom_fields'),
                     rules.Field('plugin_settings')]),
        ),
    ]



    column_labels = {
        'password': 'Attributes',
        'require_fqdn': 'Require FQDN',
        'cmdb_object': 'CMDB object',
        'restrict_to': 'Role',
        'account_jobs': 'Jobs',
        'options': 'Options',
        'shadow_mode': 'Shadow source',
        'auto_apply_templates': 'Auto Apply Templates',
    }

    form_args = {
        'require_fqdn': {'label': 'Require FQDN'},
        'cmdb_object': {'label': 'CMDB object'},
        'restrict_to': {'label': 'Role'},
        'account_jobs': {'label': 'Jobs'},
        'is_object': {'label': 'Imports as', 'coerce': bool},
        'object_type': {'label': 'Object type'},
        'shadow_mode': {'label': 'Shadow source'},
        'auto_apply_templates': {'label': 'Auto Apply Templates',
                                 'validators': [Optional()]},
    }

    @action('clear_shadow', 'Clear Shadow Source Data',
            'Remove the labels these accounts delivered as shadow source '
            'from all hosts?')
    def action_clear_shadow(self, ids):
        """Remove the shadow labels the selected accounts delivered."""
        names = [account.name for account in Account.objects(id__in=ids)]
        cleared = Host.clear_shadow_data(shadow_account_name__in=names)
        flash(f'Shadow source data removed from {cleared} host(s).', 'success')
        return redirect(request.referrer or url_for('.index_view'))

    @action('take_over_shadow', 'Go Live with Shadow Data',
            'Replace the labels of the hosts with the shadow data these '
            'accounts delivered? The accounts stop being shadow sources and '
            'become master, so they own the hosts from now on.')
    def action_take_over_shadow(self, ids):
        """Make the shadow data of the selected accounts the live labels."""
        for account in Account.objects(id__in=ids):
            if not Host.objects(shadow_account_name=account.name).count():
                flash(f'{account.name}: no shadow data to go live with.', 'warning')
                continue
            if not account.enabled:
                flash(f'{account.name}: the account is disabled.', 'danger')
                continue
            account.shadow_mode = False
            account.is_master = True
            try:
                account.save()
            except ModelValidationError as error:
                flash(f'{account.name}: {error}', 'danger')
                continue
            taken, refused = take_over_shadow_data(get_account_by_name(account.name))
            message = (f'{account.name}: shadow data of {taken} host(s) is live, '
                       'the account is master now.')
            if refused:
                message += f' {refused} host(s) refused it and keep their shadow data.'
            flash(message, 'warning' if refused else 'success')
        return redirect(request.referrer or url_for('.index_view'))

    column_formatters = {
        'password': _render_custom_data,
        'plugin_settings': _render_plugin_data,
        'type': _render_type,
        'restrict_to': _render_role,
        'options': _render_options,
    }

    form_overrides = {
        'name': StringField,
        'password': _PasswordField,
        'address': StringField,
        'username': StringField,
        'is_object': SelectField,
        'account_jobs': _JobListField,
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
        if not self.can_create:
            # Flask-Admin's own create_view bails out like this, but the
            # type picker below runs before we ever delegate to it — a
            # read-only user would otherwise be shown a create page whose
            # POST is refused.
            return redirect(self.get_url('.index_view'))
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
        form = _template_choices(super().edit_form(obj))
        _show_inventory_key(_source_choices(form), obj)
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
        form = _template_choices(super().create_form(obj))

        account_type = (request.args.get('type') or '').strip()
        _source_choices(form)
        if hasattr(form, 'object_type') and not form.object_type.data:
            # A new account imports hosts, of the object type Host Object
            form.object_type.data = 'host'
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
        _check_jobs(model, account_type)
        _store_inventory_key(form, model)
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

        return super().on_model_change(form, model, is_created)

    def on_model_delete(self, model):
        """
        Prevent deletion of Accounts with Assigned References
        """
        # Problem: Reverse Delete Rules not woking for EmbeddedDocument
        for group in CronGroup.objects():
            for job in group.jobs:
                if job_account(job) == model:
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
