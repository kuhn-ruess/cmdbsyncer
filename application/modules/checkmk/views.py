"""
Checkmk Rule Views
"""
from markupsafe import Markup

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DjangoLexer

from wtforms import HiddenField, StringField, PasswordField
from wtforms.validators import ValidationError
from flask import request
from flask_admin import expose
from flask_admin.form import rules
from mongoengine.errors import DoesNotExist

from flask_login import current_user
from application import app
from application.views.default import DefaultModelView
from application.docu_links import docu_links

from application.modules.rule.views import (
    RuleModelView,
    form_subdocuments_template,
    _render_full_conditions,
    get_rule_json,
    _render_jinja,
)
from application.modules.checkmk.models import action_outcome_types, CheckmkSite
from application.plugins.checkmk import get_debug_data

from application.models.host import Host

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
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{entry['description']}</td></tr>"
    html += "</table>"
    return Markup(html)

def _render_checkmk_outcome(_view, _context, model, _name):
    """
    Render Checkmk outcomes
    """
    html = ""
    for entry in model.outcomes:
        name = dict(action_outcome_types)[entry.action].split('_',1)[0]
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
    html = "<table width=100%>"\
           f"<tr><th>Type</th><td>{entry.group_name}</td></tr>"\
           f"<tr><th>Foreach</th><td>{entry.foreach_type}</td></tr>" \
           f"<tr><th>Value</th><td>{entry.foreach}</td></tr>" \
           f"<tr><th>Jinja Name Rewrite</th><td>{entry.rewrite}</td></tr>" \
           f"<tr><th>Jinja Title Rewrite</th><td>{entry.rewrite_title}</td></tr>" \
           "</table>"
    return Markup(html)

def get_host_debug(hostname):
    """
    Get Output for Host Debug Page
    """

    try:
        Host.objects.get(hostname=hostname)

        output = {}
        output_rules = {}

        attributes, actions, debug_log = get_debug_data(hostname)

        for type_name, data in debug_log.items():
            output_rules[type_name] = data

        if attributes:
            output["Full Attribute List"] = attributes['all']
            output["Filtered Labels for Checkmk"] = attributes['filtered']
            output["Actions"] =  actions
            additional_attributes = {}
            additional_attributes =  actions.get('custom_attributes', {})

            for additional_attr in actions.get('attributes',[]):
                if attr_value := attributes['all'].get(additional_attr):
                    additional_attributes[additional_attr] = attr_value
            output["Custom Attributes"] = additional_attributes
        else:
            output["Info: Host disabled by Filter"] = None
        return output, output_rules
    except DoesNotExist:
        return {'Error': "Host not found in Database"}, {}

#pylint: disable=too-few-public-methods
class CheckmkRuleView(RuleModelView):
    """
    Custom Rule Model View
    """

    @expose('/debug')
    def debug(self):
        """
        Checkmk specific Debug Page
        """
        if obj_id := request.args.get('obj_id'):
            hostname = Host.objects.get(id=obj_id).hostname
        else:
            hostname = request.args.get('hostname','').strip()
        output= {}
        output_rules = {}

        if hostname:
            output, output_rules = get_host_debug(hostname)

        base_urls = {
            'filter': f"{app.config['BASE_PREFIX']}admin/checkmkfilterrule/edit/?id=",
            'rewrite': f"{app.config['BASE_PREFIX']}admin/checkmkrewriteattributerule/edit/?id=",
            'actions': f"{app.config['BASE_PREFIX']}admin/checkmkrule/edit/?id=",
            'CustomAttributes': f"{app.config['BASE_PREFIX']}admin/customattributerule/edit/?id=",
        }
        new_rules = {}
        for rule_group, rule_data in output_rules.items():
            new_rules.setdefault(rule_group, [])
            for rule in rule_data:
                #if rule_group in base_urls:
                rule['rule_url'] = f"{base_urls[rule_group]}{rule['id']}"
                new_rules[rule_group].append(rule)

        if "Error" in output:
            output = f"Error: {output['Error']}"

        return self.render('debug.html', hostname=hostname, output=output,
                           rules=new_rules)


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
    html = "<table width=100%>"
    for idx, rule in enumerate(model.outcomes):
        value_template = \
                highlight(rule.value_template, DjangoLexer(),
                          HtmlFormatter(sytle='colorfull'))
        condition_service = ""
        if rule.condition_service:
            condition_service = highlight(
                rule.condition_service, DjangoLexer(),
                HtmlFormatter(sytle='colorfull')
            )
        html += f"<tr><td>{idx}</td><td>"\
               "<table width=100%>"\
               f"<tr><th>Ruleset</th><td>{rule.ruleset}</td></tr>" \
               f"<tr><th>Folder</th><td>{rule.folder}</td></tr>" \
               f"<tr><th>Folder Index</th><td>{rule.folder_index}</td></tr>" \
               f"<tr><th>Comment</th><td>{rule.comment}</td></tr>" \
               f"<tr><th>Loop:</th><td>{rule.loop_over_list}</td></tr>" \
               f"<tr><th>Value Template</th><td>{value_template}</td></tr>" \
               f"<tr><th>Condition Label Tmple</th><td>{rule.condition_label_template}</td></tr>"\
               f"<tr><th>Condition Host</th><td>{rule.condition_host}</td></tr>"\
               f"<tr><th>Condition Service</th><td>{condition_service}</td></tr>"\
               f"<tr><th>Condition Service Label</th><td>{rule.condition_service_label}</td></tr>"\
               "</table>"\
               "</td></tr>"
    html += "</table>"
    return Markup(html)

class CheckmkGroupRuleView(RuleModelView):
    """
    Custom Group Model View
    """
    column_default_sort = "name"

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
        rules.HTML(f'<i class="fa fa-info"></i><a href="{docu_links["cmk_groups"]}"'\
                        'target="_blank" class="badge badge-light">Documentation</a>'),
        rules.FieldSet(
           ('name', 'documentation', 'enabled'),
            "1. Main Options"),
        rules.FieldSet(
           ( 'outcome',
           ), "2. Rule"),
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

    form_rules = [
        rules.FieldSet((
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            ), "1. Main Options"),
            div_close,

       rules.FieldSet(
           ( 'condition_typ', 'conditions',
           ), "2. Conditions"),
       rules.FieldSet(
           ( 'outcomes',
           ), "3. BI Rule"),
    ]

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
        rules.FieldSet((
            rules.HTML(f'<i class="fa fa-info"></i><a href="{docu_links["cmk_setup_rules"]}"'\
                            'target="_blank" class="badge badge-light">Documentation</a>'),
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            ), "1. Main Options"),
            div_close,

       rules.FieldSet(
           ( 'condition_typ', 'conditions',
           ), "2. Conditions"),
       rules.FieldSet(
           ( 'outcomes',
           ), "3. Rule"),
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

        #pylint: disable=access-member-before-definition
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
                                    'Hostname for Condition, Supports Comma Seperated Lists (or)'
                                )
                            },
                            'condition_service': {
                                'placeholder': (
                                    'Service Name for Condition, Supports Comma Seperated Lists (or)'
                                )
                            },
                            'condition_service_label': {
                                'placeholder': (
                                    'Service Labels for Condition, Supports Comma Seperated Lists (and)'
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
        rules.FieldSet((
            rules.HTML(f'<i class="fa fa-info"></i><a href="{docu_links["cmk_hosttags"]}"'\
                            'target="_blank" class="badge badge-light">Documentation</a>'),
            )
       ),
       main_open,
       rules.FieldSet(
           ('group_topic_name', 'group_title', 'group_id', 'group_help',
           ), "1. Checkmk Group Data"),
       rules.FieldSet(
           ( 'rewrite_id', 'rewrite_title',
           ), "2. Define which ID and Title the Tag should have in Checkmk"),
       rules.FieldSet(
           ( 'enabled',
           ), "3. Enable"),
       main_close,
       addional_open,
       rules.FieldSet(
           ( 'group_multiply_list', 'group_multiply_by_list',
           ), 'Create Multiple Checkmk Groups'),
       rules.HTML('<br>'),
       rules.FieldSet(
           ( 'filter_by_account',
           ), 'Filter Input Data'),
        rules.FieldSet(('documentation',), 'Internal Documentation'),
        addional_close
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


    column_exclude_list = [
        'inital_password',
        'subscription_username',
        'subscription_password',
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
       'folder_name',
       'folder_seats',
       'enabled',
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
    form_rules = [
        rules.FieldSet((
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            ), "1. Main Options"),
            div_close,

       rules.FieldSet(
           ( 'condition_typ', 'conditions',
           ), "2. Conditions"),
       rules.FieldSet(
           ( 'outcomes',
           ), "3. Downtime"),
    ]

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
        rules.HTML(f'<i class="fa fa-info"></i><a href="{docu_links["cmk_inventory_attributes"]}"'\
                        'target="_blank" class="badge badge-light">Documentation</a>'),
        rules.Field('attribute_names'),
        rules.Field('attribute_source'),
    ]

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('checkmk')

class CheckmkPasswordView(DefaultModelView):
    """
    Checkmk Password View
    """

    form_rules = [
        rules.HTML(f'<i class="fa fa-info"></i><a href="{docu_links["cmk_password_store"]}"'\
                        'target="_blank" class="badge badge-light">Documentation</a>'),
       main_open,
       rules.FieldSet(
           ('name', 'documentation', 'enabled'),
            "Documentation"),
       main_close,
       checkmk_open,
       rules.FieldSet(
           ( 'title', 'comment', 'documentation_url', 'owner', 'password', 'shared',
           ), "Fields for Checkmk's Password Store"),
        checkmkl_close,
    ]

    column_filters = [
        'title',
        'comment',
    ]

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
