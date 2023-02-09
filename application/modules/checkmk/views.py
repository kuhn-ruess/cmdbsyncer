"""
Checkmk Rule Views
"""
from markupsafe import Markup
from wtforms import HiddenField
from flask import request
from flask_admin import expose
from mongoengine.errors import DoesNotExist

from flask_login import current_user
from application.views.default import DefaultModelView

from application.modules.rule.views import RuleModelView
from application.modules.checkmk.models import action_outcome_types
from application.plugins.checkmk import _load_rules
from application.modules.checkmk.syncer import SyncCMK2

from application.models.host import Host

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
           f"<tr><th>Regex</th><td>{entry.regex}</td></tr>" \
           "</table>"
    return Markup(html)

def get_host_debug(hostname):
    """
    Get Output for Host Debug Page
    """

    rules = _load_rules()

    syncer = SyncCMK2()
    syncer.filter = rules['filter']

    syncer.rewrite = rules['rewrite']

    syncer.actions = rules['actions']

    output = {}
    #'Filter Rules': rules['filter'],
    #'Rewrite Rules': rules['rewrite'],
    #'Action Rules': rules['actions'],
    #}

    try:
        db_host = Host.objects.get(hostname=hostname)
    except DoesNotExist:
        return {'Error': "Host not found in Database"}

    attributes = syncer.get_host_attributes(db_host)

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
               f"<tr><th>Condition Label Template</th><td>{rule.condition_label_template}</td></tr>"\
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
        del self.form_subdocuments['conditions']

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

class CheckmkMngmtRuleView(RuleModelView):
    """
    Custom Group Model View
    """

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
                }
            }
        }
    }

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
