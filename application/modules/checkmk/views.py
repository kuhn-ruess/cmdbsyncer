"""
Checkmk Rule Views
"""
from markupsafe import Markup
from wtforms import HiddenField, StringField
from wtforms.validators import ValidationError
from flask import request
from flask_admin import expose
from flask_admin.form import rules
from mongoengine.errors import DoesNotExist

from flask_login import current_user
from application.views.default import DefaultModelView

from application.modules.rule.views import RuleModelView, divider, _render_full_conditions
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

    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        # Evil hack: Field not exists here,
        # but RuleModelView defines it -> Error
        if 'conditions' in self.form_subdocuments:
            del self.form_subdocuments['conditions']

        # Default Form rules not match for the Fields of this Form
        self.form_rules = []

        self.column_formatters.update({
            'render_checkmk_group_outcome': _render_group_outcome,
        })

        self.form_overrides.update({
            'render_checkmk_group_outcome': HiddenField,
        })

        self.column_labels.update({
            'render_checkmk_group_outcome': "Create following Groups",
        })

        super().__init__(model, **kwargs)


class CheckmkBiRuleView(DefaultModelView):
    """
    Custom BI Rule View
    """

    form_excluded_columns = (
        'render_full_conditions',
        'render_cmk_bi_aggregation',
    )

    #@TODO: Fix that it's not possible just to reference to from_subdocuments_template
    form_subdocuments = {
        'conditions': {
            'form_subdocuments' : {
                None: {
                    'form_widget_args': {
                        'hostname_match': {'style': 'background-color: #2EFE9A;' },
                        'hostname': { 'style': 'background-color: #2EFE9A;' },
                        'tag_match': { 'style': 'background-color: #81DAF5;' },
                        'tag': { 'style': 'background-color: #81DAF5;' },
                        'value_match': { 'style': 'background-color: #81DAF5;' },
                        'value': { 'style': 'background-color: #81DAF5;'},
                    },
                    'form_overrides' : {
                        'hostname': StringField,
                        'tag': StringField,
                        'value': StringField,
                    },
                    'form_rules' : [
                        rules.FieldSet(('match_type',), "Condition Match Type"),
                        rules.HTML(divider % "Match on Host"),
                        rules.FieldSet(
                            ('hostname_match', 'hostname', 'hostname_match_negate'), "Host Match"),
                        rules.HTML(divider % "Match on Attribute"),
                        rules.FieldSet(
                            (
                                'tag_match', 'tag', 'tag_match_negate',
                                'value_match', 'value', 'value_match_negate',
                            ), "Attribute Match"),
                    ]
                }
            }
        },
        'outcomes' : {
            'form_subdocuments' : {
                None: {
                    'form_widget_args': {
                        'rule_template' : {"rows": 10},
                    },
                }
            }
        }
    }

    column_formatters = {
        'render_full_conditions': _render_full_conditions,
        'render_cmk_bi_rule': _render_bi_rule,
    }

    column_labels = {
        'render_cmk_bi_rule': "Rules",
        'render_full_conditions': "Conditions",
    }

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


class CheckmkMngmtRuleView(RuleModelView):
    """
    Custom Group Model View
    """

    #@TODO: Fix that it's not possible just to reference to from_subdocuments_template
    form_subdocuments = {
        'conditions': {
            'form_subdocuments' : {
                None: {
                    'form_widget_args': {
                        'hostname_match': { 'style': 'background-color: #2EFE9A' },
                        'hostname': { 'style': 'background-color: #2EFE9A' },
                        'tag_match': { 'style': 'background-color: #81DAF5' },
                        'tag': { 'style': 'background-color: #81DAF5' },
                        'value_match': { 'style': 'background-color: #81DAF5' },
                        'value': { 'style': 'background-color: #81DAF5' },
                    },
                    'form_overrides' : {
                        'hostname': StringField,
                        'tag': StringField,
                        'value': StringField,
                    },
                    'form_rules' : [
                        rules.FieldSet(('match_type',), "Condition Match Type"),
                        rules.HTML(divider % "Match on Host"),
                        rules.FieldSet(
                            ('hostname_match', 'hostname', 'hostname_match_negate'), "Host Match"),
                        rules.HTML(divider % "Match on Attribute"),
                        rules.FieldSet(
                            (
                                'tag_match', 'tag', 'tag_match_negate',
                                'value_match', 'value', 'value_match_negate',
                            ), "Attribute Match"),
                    ]
                }
            }
        }
    }

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
class CheckmkTagMngmtView(DefaultModelView):
    """
    Checkmk Tag Management
    """

    column_exclude_list = []


class CheckmkUserMngmtView(DefaultModelView):
    """
    Checkmk User Management
    """

    column_exclude_list = [
        'password', 'email',
        'pager_address'
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
