"""
Checkmk Rule Views
"""
# pylint: disable=too-many-lines
# pylint: disable=duplicate-code
from markupsafe import Markup, escape

from pygments import highlight
from pygments.formatters import HtmlFormatter  # pylint: disable=no-name-in-module
from pygments.lexers import DjangoLexer  # pylint: disable=no-name-in-module

from wtforms import HiddenField, StringField, PasswordField
from wtforms.validators import ValidationError
from flask_admin.form import rules
from flask_admin.actions import action
from flask_admin.base import expose
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike
from flask import redirect, url_for, request, render_template, flash

from flask_login import current_user
from application.views.default import DefaultModelView
from application.docu_links import docu_links

from application.modules.rule.views import (
    RuleModelView,
    form_subdocuments_template,
    _render_full_conditions,
    get_rule_json,
    _render_jinja,
    _modern_rule_form,
)
from application.views._form_sections import modern_form, section
from .models import action_outcome_types, CheckmkSite, CheckmkSettings


div_open = rules.HTML('<div class="form-check form-check-inline">')
div_close = rules.HTML("</div>")

main_open = rules.HTML('<div class="card">'\
        '<h5 class="card-header">Main Options</h5>'\
        '<div class="card-body">')
main_close = rules.HTML("</div></div><br>")

checkmk_open = rules.HTML('<div class="card">'\
        '<h5 class="card-header">Checkmk Options</h5>'\
        '<div class="card-body">')
checkmkl_close = rules.HTML("</div></div>")

addional_open = rules.HTML('<div class="card">'\
    '<h5 class="card-header">Addional Options</h5>'\
        '<div class="card-body">')
addional_close = rules.HTML("</div></div>")

def _render_dw_rule(_view, _context, model, _name):
    """
    Render Downtime Rule
    """
    html = ""
    for idx, entry in enumerate(model.outcomes):
        idx += 1
        data = [
            ("Every", entry['every']),
            ("Day", entry['start_day']),
            ("Hour", entry['start_time_h']),
            ("Min", entry['start_time_m']),
        ]
        out_lines = ""
        for what, value in data:
            if not value:
                continue
            highlighted = \
                    highlight(value, DjangoLexer(),
                              HtmlFormatter(sytle='colorfull'))
            out_lines += f"{what}: {highlighted}"

        html += f'''
            <div class="card">
              <div class="card-body">
                <p class="card-text">
                 <h6 class="card-subtitle mb-2 text-muted">Downtime {idx}</h6>
                </p>
                  {out_lines}
              </div>
            </div>
            '''

    return Markup(html)


def _render_dcd_rule(_view, _context, model, _name):
    """
    Render Downtime Rule
    """

    html = ""
    for entry in model.outcomes:
        dcd_id = \
                highlight(str(entry['dcd_id']), DjangoLexer(),
                          HtmlFormatter(sytle='colorfull'))
        title  = \
                highlight(str(entry['title']), DjangoLexer(),
                          HtmlFormatter(sytle='colorfull'))
        html += f'''
            <div class="card">
              <div class="card-body">
                <p class="card-text">
                 <h6 class="card-subtitle mb-2 text-muted">{dcd_id}</h6>
                 {title}
                </p>
              </div>
            </div>
            '''
    return Markup(html)

def _render_bi_rule(_view, _context, model, _name):
    """
    Render BI Rule
    """
    html = '''
        <div class="card">
            <div class="card-body">
            <p class="card-text">
            <ul class="list-group">
    '''
    for idx, entry in enumerate(model.outcomes):
        html += f"<li class='list-group-item'>{idx}: {escape(entry['description'])}</li>"
    html += '''
            </ul>
            </p>
            </div>
        </div>
    '''
    return Markup(html)

def _render_checkmk_outcome(_view, _context, model, _name):
    """
    Render Checkmk outcomes
    """
    html = ""
    for entry in model.outcomes:
        name = escape(dict(action_outcome_types)[entry.action].split('_',1)[0])
        highlighted_param = ""
        if entry.action_param:
            highlighted_param = highlight(
                str(entry.action_param),
                DjangoLexer(),
                HtmlFormatter(sytle='colorfull')
            )
        html += f'''
            <div class="card">
              <div class="card-body">
                <p class="card-text">
                 <h6 class="card-subtitle mb-2 text-muted">{name}</h6>
                </p>
                <p class="card-text">
                {highlighted_param}
                </p>
              </div>
            </div>
            '''

    return Markup(html)

def _render_group_outcome(_view, _context, model, _name):
    """
    Render Group Outcome
    """
    entry = model.outcome
    html = f'''
        <div class="card">
            <div class="card-body">
            <p class="card-text">
                <h6 class="card-subtitle mb-2 text-muted">{escape(entry.group_name)}</h6>
            </p>
            <p class="card-text">
            <ul>
            <li>Foreach: {escape(entry.foreach_type)}</li>
            <li>Value: {escape(entry.foreach)}</li>
            <li>Jinja Name Rewrite: {escape(entry.rewrite)}</li>
            <li>Jinja Title Rewrite: {escape(entry.rewrite_title)}</li>
            </ul>
            </p>
            </div>
        </div>
    '''
    return Markup(html)


class CheckmkRuleView(RuleModelView):
    """
    Custom Rule Model View
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        self.column_formatters.update({
            'render_checkmk_outcome': _render_checkmk_outcome,
        })

        self.form_overrides.update({
            'render_checkmk_outcome': HiddenField,
        })

        self.column_labels.update({
            'render_checkmk_outcome': "Checkmk Outcomes",
        })

        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments' : {
                    '': {
                        'form_overrides' : {
                            #'action_param': StringField,
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')


def _render_rule_mngmt_outcome(_view, _context, model, _name):
    """
    Render Group Outcome
    """
    html = ""
    for _idx, rule in enumerate(model.outcomes):
        value_template = \
                highlight(rule.value_template, DjangoLexer(),
                          HtmlFormatter(sytle='colorfull'))
        html += f'''
           <div class="card">
             <div class="card-body">
               <p class="card-text">
                <h5 class="card-title mb-2">{escape(rule.ruleset)}</h5>
               </p>
               <p class="card-text">
               <ul>
                <li><b>Template</b>: {value_template}</li>
        '''
        if rule.loop_over_list:
            html += f'''
                   <li><b>Loop over</b>: {escape(rule.list_to_loop)}</li>
            '''
        html += "</ul></p>"
        html += '''
               <p class="card-text">
                <h6 class="card-subtitle mb-2">Conditions:</h6>
               </p>
               <p class="card-text">
               <ul>
        '''
        if rule.condition_host:
            html += f'<li><b>Host</b>: {escape(rule.condition_host)}</li>'
        if rule.condition_label_template:
            html += f'<li><b>Host Label</b>: {escape(rule.condition_label_template)}</li>'
        if rule.condition_service:
            html += f'<li><b>Service</b>: {escape(rule.condition_service)}</li>'
        if rule.condition_service_label:
            html += f'<li><b>Service Label</b>: {escape(rule.condition_service_label)}</li>'
        html += '''
                   </ul>
                   </p>
                 </div>
               </div>
            '''
    return Markup(html)

class CheckmkGroupRuleView(RuleModelView):
    """
    Custom Group Model View
    """
    column_default_sort = "name"

    column_exclude_list = [
        'conditions', 'outcomes', 'outcome',
    ]

    form_subdocuments = {
        'outcome': {
            'form_overrides': {
                'foreach': StringField,
                'rewrite': StringField,
                'rewrite_title': StringField,
            },
            'form_widget_args': {
                'foreach': {
                    'placeholder': (
                        'Name of Attribute or Attribute Value, '
                        'depending on Foreach Type. You can use *'
                    )
                },
                'rewrite': {'placeholder': '{{name}}'},
                'rewrite_title': {'placeholder': '{{name}}'},
            }
        },
    }

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_groups"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Main Options',
                    'Name, description and activation.',
                    [rules.Field('name'),
                     rules.Field('documentation'),
                     rules.Field('enabled')]),
            section('2', 'out', 'Group Outcome',
                    'Create host/contact/service groups for hosts this '
                    'rule matches on.',
                    [rules.Field('outcome')]),
        ),
    ]


    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        # Default Form rules not match for the Fields of this Form
        #self.form_rules = []

        self.column_formatters.update({
            'render_checkmk_group_outcome': _render_group_outcome,
        })

        self.form_overrides.update({
            'render_checkmk_group_outcome': HiddenField,
            'name': StringField,
        })


        self.column_labels.update({
            'render_checkmk_group_outcome': "Create following Groups",
        })

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')



bi_rule_template = form_subdocuments_template.copy()
bi_rule_template.update({
        'outcomes' : {
            'form_subdocuments' : {
                '': {
                    'form_widget_args': {
                        'rule_template' : {"rows": 10},
                    },
                }
            }
        }
    })

class CheckmkBiRuleView(DefaultModelView):
    """
    Custom BI Rule View
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    form_rules = _modern_rule_form(
        main_fields=[
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            div_close,
        ],
        condition_fields=[
            rules.Field('condition_typ'),
            rules.Field('conditions'),
        ],
        outcome_fields=[rules.Field('outcomes')],
        outcome_title='BI Rule',
        outcome_desc='Business Intelligence rule pushed into Checkmk.',
    )

    form_excluded_columns = (
        'render_full_conditions',
        'render_cmk_bi_aggregation',
    )

    column_editable_list = [
        'enabled',
    ]

    form_subdocuments = bi_rule_template

    column_formatters = {
        'render_full_conditions': _render_full_conditions,
        'render_cmk_bi_rule': _render_bi_rule,
    }

    column_labels = {
        'render_cmk_bi_rule': "Rules",
        'render_full_conditions': "Conditions",
    }

    column_exclude_list = [
        'conditions', 'outcomes',
    ]

    form_overrides = {
        'render_cmk_bi_rule': HiddenField,
    }

    def on_model_change(self, form, model, is_created):
        """
        Cleanup Inputs
        """
        for rule in model.outcomes:
            rule.rule_template = rule.rule_template.replace('\\n',' ')
            rule.rule_template = rule.rule_template.replace('false','False')
            rule.rule_template = rule.rule_template.replace('true','True')

        return super().on_model_change(form, model, is_created)

    def __init__(self, model, **kwargs):
        """
        """
        #self.form_subdocuments = bi_rule_template
        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')



class CheckmkMngmtRuleView(RuleModelView):
    """
    Management of Rules inside Checkmk
    """
    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_setup_rules"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *_modern_rule_form(
            main_fields=[
                rules.Field('name'),
                rules.Field('documentation'),
                div_open,
                rules.NestedRule(('enabled', 'last_match')),
                div_close,
            ],
            condition_fields=[
                rules.Field('condition_typ'),
                rules.Field('conditions'),
            ],
            outcome_fields=[rules.Field('outcomes')],
            outcome_title='Checkmk Setup Rule',
            outcome_desc='The actual ruleset entry to create inside '
                         'Checkmk for matching hosts.',
        ),
    ]

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        self.column_formatters.update({
            'render_cmk_rule_mngmt': _render_rule_mngmt_outcome,
        })

        self.form_overrides.update({
            'render_cmk_rule_mngmt': HiddenField,
        })

        self.column_labels.update({
            'render_cmk_rule_mngmt': "Create following Rules",
        })

        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments' : {
                    '': {
                        'form_overrides' : {
                            'ruleset': StringField,
                            'folder': StringField,
                            'condition_host': StringField,
                            'list_to_loop': StringField,
                            'value_template': StringField,
                            'condition_label_template': StringField,
                            'condition_service_label': StringField,
                            'condition_service': StringField,
                        },
                        'form_widget_args': {
                            'list_to_loop': {
                                'placeholder': (
                                    'You can enter an Attribute which contains a List.'
                                    ' Then the rule will be executed for every entry in this list.'
                                )
                            },
                            'value_template': {
                                'placeholder': (
                                    'Jinja. You can use {{loop}} to access variable'
                                    'when used in loop list mode'
                                )
                            },
                            'condition_label_template': {
                                'placeholder': (
                                    'Jinja. Need to return key:value'
                                )
                            },
                            'condition_host': {
                                'placeholder': (
                                    'Hostname for Condition, Supports'
                                    ' Comma Seperated Lists (or).'
                                    ' Use {{HOSTNAME}} for actual Host'
                                )
                            },
                            'condition_service': {
                                'placeholder': (
                                    'Service Name for Condition,'
                                    ' Supports Comma Seperated'
                                    ' Lists (or)'
                                )
                            },
                            'condition_service_label': {
                                'placeholder': (
                                    'Service Labels for Condition,'
                                    ' Supports Comma Seperated'
                                    ' Lists (and)'
                                )
                            },
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config


        super().__init__(model, **kwargs)

    def on_model_change(self, form, model, is_created):
        """
        Cleanup Inputs
        """
        for rule in model.outcomes:
            if rule.value_template[0] == '"':
                rule.value_template = rule.value_template[1:]
            if rule.value_template[-1] == '"':
                rule.value_template = rule.value_template[:-1]
            rule.value_template = rule.value_template.replace('\\n',' ')

        return super().on_model_change(form, model, is_created)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')


class CheckmkSiteView(DefaultModelView):
    """
    Checkmk Site Management Config
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    column_default_sort = "name"


    column_editable_list = [
        'enabled',
    ]

    form_rules = modern_form(
        section('1', 'main', 'Basics',
                'Name of the Checkmk site, description and activation.',
                [rules.Field('name'),
                 rules.Field('documentation'),
                 rules.Field('enabled')]),
        section('2', 'cond', 'Connection',
                'Server address and the Site Settings template to '
                'inherit (edition, version, certs, …).',
                [rules.Field('server_address'),
                 rules.Field('settings_master')]),
        section('3', 'out', 'Ansible Overrides',
                'Per-site custom Ansible variables applied on top of '
                'the Site Settings defaults.',
                [rules.Field('custom_ansible_variables')]),
    )

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')


class CheckmkTagMngmtView(DefaultModelView):
    """
    Checkmk Tag Management
    """

    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }
    form_widget_args = {
        'group_topic_name': {
            'placeholder': 'Name of Topic for Hosttags in Checkmk'
        },
        'group_title': {
            'placeholder': 'Groups Title'
        },
        'rewrite_title': {
            'placeholder': '{{name}}'
        },
        'rewrite_id': {
            'placeholder': '{{name}}'
        },
        'group_multiply_list': {
            'placeholder': (
                'Name of Attribute containing the list of values to '
                'create multiple groups'
            )
        },
    }

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_hosttags"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Checkmk Group Data',
                    'Topic, title, id and help text that appear in '
                    'Checkmk Setup.',
                    [rules.Field('group_topic_name'),
                     rules.Field('group_title'),
                     rules.Field('group_id'),
                     rules.Field('group_help')]),
            section('2', 'cond', 'ID & Title Rewrites',
                    'Define which ID and title the tag should have in Checkmk.',
                    [rules.Field('rewrite_id'),
                     rules.Field('rewrite_title'),
                     rules.Field('enabled')]),
            section('3', 'aux', 'Additional Options',
                    'Create multiple groups, filter input, internal notes.',
                    [rules.Field('group_multiply_list'),
                     rules.Field('group_multiply_by_list'),
                     rules.Field('filter_by_account'),
                     rules.Field('documentation')]),
        ),
    ]

    form_overrides = {
        'group_topic_name': StringField,
        'group_title': StringField,
        'group_id': StringField,
        'group_help': StringField,
    }

    column_exclude_list = [
        'documentation', 'group_help',

    ]
    column_editable_list = [
        'enabled',
    ]

    column_formatters = {
            'rewrite_id': _render_jinja,
            'rewrite_title': _render_jinja,
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')



class CheckmkUserMngmtView(DefaultModelView):
    """
    Checkmk User Management
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }


    column_exclude_list = [
        'password', 'email',
        'pager_address'
    ]

    column_editable_list = [
        'disabled',
        'remove_if_found',
        'disable_login'
    ]

    form_rules = modern_form(
        section('1', 'main', 'Identity',
                'Login ID, name and contact — these are the fields '
                'Checkmk shows in the user list.',
                [rules.Field('user_id'),
                 rules.Field('full_name'),
                 rules.Field('email'),
                 rules.Field('pager_address'),
                 rules.Field('documentation')]),
        section('2', 'cond', 'Roles & Groups',
                'Which Checkmk roles and contact groups this user '
                'belongs to.',
                [rules.Field('roles'),
                 rules.Field('contact_groups')]),
        section('3', 'out', 'Authentication',
                'Password handling and login state on the Checkmk side.',
                [rules.Field('password'),
                 rules.Field('overwrite_password'),
                 rules.Field('force_password_change'),
                 rules.Field('disable_login')]),
        section('4', 'aux', 'Lifecycle',
                'Sync flags controlling how this user entry reacts to '
                'the Checkmk state.',
                [rules.Field('remove_if_found'),
                 rules.Field('disabled')]),
    )

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')



class CheckmkSettingsView(DefaultModelView):
    """
    Checkmk Server Settings View
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    form_widget_args = {
        'cmk_version_filename': {
            'placeholder': (
                'Filename of installation file. '
                'You can use {{CMK_VERSION}} and {{CMK_EDITION}} as placeholders'
            )
        },
        'cmk_version': {
            'placeholder': "Target Checkmk Version Number",
        },
        'server_user': {
            'placeholder': "User to connect to server where the site is running",
        },
        'inital_password': {
            'placeholder': "Initial Passwort if we need to create the site",
        },
        'subscription_username': {
            'placeholder': (
                "Enter Data if you want the syncer to download this "
                "Versions directly from checkmk"
            ),
        },
        'cmk_user': {
            'placeholder': (
                "API user for CheckMK automation"
                " (for downtime management)."
                " You can use {{ACCOUNT:x:username}}"
                " as Placeholder"
            ),
        },
        'cmk_secret': {
            'placeholder': (
                "API secret/password for CheckMK"
                " automation ({{ACCOUNT:x:password}}"
            ),
        },
        'cmk_server_address': {
            'placeholder': (
                "CheckMK server address for API calls"
                " (with site, or {{ACCOUNT:x:address}})"
            ),
        },
        'webserver_certificate': {
            'placeholder': (
                "Optional: Add Paths to your Webserver Certificate Files "
                "to automaticly update them if needed"
            ),
        },
    }

    form_rules = modern_form(
        section('1', 'main', 'Basics',
                'Name, documentation and the Ansible user for site ops.',
                [rules.Field('name'),
                 rules.Field('documentation'),
                 rules.Field('server_user')]),
        section('2', 'cond', 'Checkmk Site',
                'Edition, version, filename and initial password — used '
                'when rolling out a fresh site.',
                [rules.Field('cmk_edition'),
                 rules.Field('cmk_version'),
                 rules.Field('cmk_version_filename'),
                 rules.Field('inital_password')]),
        section('3', 'out', 'Checkmk API',
                'Optional: credentials + API address for automated '
                'downtimes / status reads.',
                [rules.Field('cmk_user'),
                 rules.Field('cmk_secret'),
                 rules.Field('cmk_server_address')]),
        section('4', 'aux', 'Automatic Download & Certificates',
                'Optional: subscription creds for auto-version-download '
                'and paths to webserver certs for auto-renewal.',
                [rules.Field('subscription_username'),
                 rules.Field('subscription_password'),
                 rules.Field('webserver_certificate'),
                 rules.Field('webserver_certificate_private_key'),
                 rules.Field('webserver_certificate_intermediate')]),
    )

    column_exclude_list = [
        'inital_password',
        'subscription_username',
        'subscription_password',
        'cmk_secret',
    ]

    column_sortable_list = (
        'name',
    )

    def on_model_delete(self, model):
        """
        Prevent deletion of Sites with Assignes configs
        """
        for site in CheckmkSite.objects():
            if site.settings_master == model:
                raise ValidationError(f"Can't delete: Still used by a Siteconfig {site.name}")

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

    list_template = 'admin/checkmk_settings_list.html'

    # Modernized list template intercepts the action client-side and
    # opens a modal instead of navigating to /set_cmk_version_form.
    # The redirect path below remains as a graceful fallback for
    # JS-disabled clients.
    @action('set_cmk_version', 'Set CMK Version', None)
    def action_set_cmk_version(self, ids):
        """
        Action to set CMK Version for selected Entries
        """
        url = url_for('.set_cmk_version_form', ids=','.join(ids))
        return redirect(url)

    @expose('/set_cmk_version_form')
    def set_cmk_version_form(self):
        """
        Custom form for CMK Version selection
        """
        ids = [str(escape(i)) for i in request.args.get('ids', '').split(',')]

        return render_template('admin/set_cmk_version_form.html', ids=ids)

    @expose('/process_cmk_version_assignment', methods=['POST'])
    def process_cmk_version_assignment(self):
        """
        Process the CMK Version assignment
        """
        rule_ids = request.form.get('rule_ids', '').split(',')
        cmk_version = request.form.get('cmk_version', '').strip()

        if not cmk_version:
            flash('Please enter a CMK Version', 'error')
            return redirect(url_for('.index_view'))

        updated_count = 0
        try:
            for rule_id in rule_ids:
                if not rule_id.strip():
                    continue
                entry = CheckmkSettings.objects(id=rule_id).first()
                if entry:
                    entry.cmk_version = cmk_version
                    entry.save()
                    updated_count += 1
            flash(f'CMK Version "{cmk_version}" applied to {updated_count} entries', 'success')
        except (ValueError, ValidationError) as e:
            flash(f'Error applying CMK Version: {str(e)}', 'error')

        return redirect(url_for('.index_view'))


class CheckmkFolderPoolView(DefaultModelView):
    """
    Folder Pool Model
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    column_default_sort = "folder_name"

    column_editable_list = [
        'enabled',
    ]

    column_filters = (
       FilterLike(
            "folder_name",
           'Folder Name'
       ),
       BooleanEqualFilter(
            "enabled",
           'Enabled'
       )
    )

    form_widget_args = {
        'folder_seats_taken': {'disabled': True},
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

    def on_model_change(self, form, model, is_created):
        """
        Make Sure Folder are saved correct
        """

        if not  model.folder_name.startswith('/'):
            model.folder_name = "/" + model.folder_name

        return super().on_model_change(form, model, is_created)

class CheckmkDowntimeView(RuleModelView):
    """
    Checkmk Downtimes
    """
    # Custom Form Rules because default needs the sort_field which we not have
    form_rules = _modern_rule_form(
        main_fields=[
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            div_close,
        ],
        condition_fields=[
            rules.Field('condition_typ'),
            rules.Field('conditions'),
        ],
        outcome_fields=[rules.Field('outcomes')],
        outcome_title='Downtime',
        outcome_desc='Schedule a Checkmk downtime window for matching hosts.',
    )

    column_labels = {
        'render_cmk_downtime_rule': "Downtimes",
        'render_full_conditions': "Conditions",
    }

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        self.column_formatters.update({
            'render_cmk_downtime_rule': _render_dw_rule,
        })

        self.form_overrides.update({
            'render_cmk_downtime_rule': HiddenField,
            'name': StringField,
        })

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

class CheckmkCacheView(DefaultModelView):
    """
    Checkmk Cache View
    """
    can_create = False
    can_edit = False
    show_details = True

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

class CheckmkDCDView(RuleModelView):
    """
    Custom DCD Rule View
    """

    column_editable_list = [
        'enabled',

    ]

    column_labels = {
        'render_cmk_dcd_rule': "DCD Rules",
        'render_full_conditions': "Conditions",
    }


    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        self.column_formatters.update({
            'render_cmk_dcd_rule': _render_dcd_rule,
        })

        self.form_overrides.update({
            'render_cmk_dcd_rule': HiddenField,
        })

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

class CheckmkInventorizeAttributesView(DefaultModelView):
    """
    Form rules for Inventorize Attributes
    """
    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_inventory_attributes"]}" '
                   f'target="_blank" class="badge badge-light" '
                   f'style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Attributes to Inventorize',
                    'Which host attributes to pull from Checkmk into '
                    'the syncer inventory.',
                    [rules.Field('attribute_names'),
                     rules.Field('attribute_source')]),
        ),
    ]

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

class CheckmkPasswordView(DefaultModelView):
    """
    Checkmk Password View
    """

    form_rules = [
        rules.HTML(f'<a href="{docu_links["cmk_password_store"]}" target="_blank" '
                   f'class="badge badge-light" style="margin-bottom: 8px;">'
                   f'<i class="fa fa-info-circle"></i> Documentation</a>'),
        *modern_form(
            section('1', 'main', 'Basics',
                    'Internal name, notes and activation.',
                    [rules.Field('name'),
                     rules.Field('documentation'),
                     rules.Field('enabled')]),
            section('2', 'out', "Checkmk Password Store",
                    'Fields synced into Checkmk\'s built-in password store.',
                    [rules.Field('title'),
                     rules.Field('comment'),
                     rules.Field('documentation_url'),
                     rules.Field('owner'),
                     rules.Field('password'),
                     rules.Field('shared')]),
        ),
    ]

    column_filters = (
       FilterLike(
            "title",
           'Title'
       ),
       FilterLike(
            "comment",
           'Comment'
       ),
    )

    column_editable_list = [
        'enabled'

    ]

    form_excluded_columns = [
       "password_crypted"
    ]

    column_exclude_list = [
        'password_crypted', 'shared', 'documentation_url',
        'owner',
    ]

    def scaffold_form(self):
        form_class = super().scaffold_form()
        form_class.password = PasswordField("Password")
        return form_class

    def on_model_change(self, form, model, is_created):
        if form.password.data:
            model.set_password(form.password.data)
        return super().on_model_change(form, model, is_created)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')
