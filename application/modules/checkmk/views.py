"""
Checkmk Rule Views
"""
from markupsafe import Markup
from wtforms import HiddenField, StringField
from wtforms.validators import ValidationError
from flask import request
from flask_admin import expose
from mongoengine.errors import DoesNotExist

from flask_login import current_user
from application.views.default import DefaultModelView

from application.modules.rule.views import RuleModelView, \
                    form_subdocuments_template, _render_full_conditions
from application.modules.checkmk.models import action_outcome_types, CheckmkSite
from application.plugins.checkmk import _load_rules
from application.modules.checkmk.syncer import SyncCMK2

from application.models.host import Host

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
    Render Label outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{dict(action_outcome_types)[entry.action]}</td>"
        if entry.action_param:
            html += f"<td><b>{entry.action_param}</b></td></tr>"
    html += "</table>"
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

    debug_rules = _load_rules()

    syncer = SyncCMK2()
    syncer.filter = debug_rules['filter']

    syncer.rewrite = debug_rules['rewrite']

    syncer.actions = debug_rules['actions']

    output = {}

    try:
        db_host = Host.objects.get(hostname=hostname)
    except DoesNotExist:
        return {'Error': "Host not found in Database"}

    attributes = syncer.get_host_attributes(db_host, 'checkmk')

    if not attributes:
        return {"Error": "This host is ignored by a rule"}

    actions = syncer.get_host_actions(db_host, attributes['all'])


    output["Full Attribute List"] = attributes['all']
    output["Filtered Labels for Checkmk"] = attributes['filtered']
    output["Actions"] =  actions
    additional_attributes = {}
    for custom_attr in actions.get('custom_attributes', []):
        additional_attributes.update(custom_attr)

    for additional_attr in actions.get('attributes',[]):
        if attr_value := attributes['all'].get(additional_attr):
            additional_attributes[additional_attr] = attr_value
    output["Custom Attributes"] = additional_attributes
    # We need to save the host,
    # Otherwise, if a rule with folder pools is executed at first time here,
    # the seat will be locked, but not saved by the host
    db_host.save()
    return output

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
        hostname = request.args.get('hostname','')
        output= {}
        if hostname:
            output = get_host_debug(hostname)
        return self.render('debug.html', hostname=hostname, output=output)

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
                            'action_param': StringField,
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)

def _render_rule_mngmt_outcome(_view, _context, model, _name):
    """
    Render Group Outcome
    """
    html = "<table width=100%>"
    for idx, rule in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>"\
               "<table width=100%>"\
               f"<tr><th>Ruleset</th><td>{rule.ruleset}</td></tr>" \
               f"<tr><th>Folder</th><td>{rule.folder}</td></tr>" \
               f"<tr><th>Folder Index</th><td>{rule.folder_index}</td></tr>" \
               f"<tr><th>Comment</th><td>{rule.comment}</td></tr>" \
               f"<tr><th>Value Template</th><td>{rule.value_template}</td></tr>" \
               f"<tr><th>Condition Label Tmple</th><td>{rule.condition_label_template}</td></tr>"\
               f"<tr><th>Condition Host</th><td>{rule.condition_host}</td></tr>"\
               "</table>"\
               "</td></tr>"
    html += "</table>"
    return Markup(html)

class CheckmkGroupRuleView(RuleModelView):
    """
    Custom Group Model View
    """


    form_subdocuments = {
        'outcome': {
            'form_overrides' : {
                'foreach': StringField,
                'rewrite': StringField,
                'rewrite_title': StringField,
            }
        },
    }


    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        # Default Form rules not match for the Fields of this Form
        self.form_rules = []

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


class CheckmkMngmtRuleView(RuleModelView):
    """
    Custom Group Model View
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        # Default Form rules not match for the Fields of this Form
        self.form_rules = []

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

class CheckmkSiteView(DefaultModelView):
    """
    Checkmk Site Management Config
    """

    column_default_sort = "name"


    column_editable_list = [
        'enabled',
    ]

class CheckmkTagMngmtView(DefaultModelView):
    """
    Checkmk Tag Management
    """

    column_exclude_list = []
    column_editable_list = [
        'enabled',
    ]


class CheckmkUserMngmtView(DefaultModelView):
    """
    Checkmk User Management
    """

    column_exclude_list = [
        'password', 'email',
        'pager_address'
    ]

    column_editable_list = [
        'disabled',
        'remove_if_found',
        'disable_login'
    ]


class CheckmkSettingsView(DefaultModelView):
    """
    Checkmk Server Settings View
    """

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

class CheckmkFolderPoolView(DefaultModelView):
    """
    Folder Pool Model
    """
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
        return current_user.is_authenticated

    def on_model_change(self, form, model, is_created):
        """
        Make Sure Folder are saved correct
        """

        if not  model.folder_name.startswith('/'):
            model.folder_name = "/" + model.folder_name

        return super().on_model_change(form, model, is_created)

class CheckmkCacheView(DefaultModelView):
    """
    Checkmk Cache View
    """
    can_create = False
    can_edit = False
    show_details = True

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated
