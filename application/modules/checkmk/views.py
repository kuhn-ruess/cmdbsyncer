"""
Checkmk Rule Views
"""
from markupsafe import Markup
from wtforms import HiddenField

from flask_login import current_user
from application.views.default import DefaultModelView

from application.modules.rule.views import RuleModelView
from application.modules.checkmk.models import action_outcome_types

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


#pylint: disable=too-few-public-methods
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

        super().__init__(model, **kwargs)

def _render_rule_mngmt_outcome(_view, _context, model, _name):
    """
    Render Group Outcome
    """
    html = "<table width=100%>"\
           "<tr><td colspan=2>"
    for rule in model.outcomes:
        html += "<table width=100%>"\
               f"<tr><th>Folder</th><td>{rule.folder}</td></tr>" \
               f"<tr><th>Folder Index</th><td>{rule.folder_index}</td></tr>" \
               f"<tr><th>Comment</th><td>{rule.comment}</td></tr>" \
               f"<tr><th>Value Template</th><td>{rule.value_template}</td></tr>" \
               f"<tr><th>Condtion Label Template</th><td>{rule.condition_label_template}</td></tr>"\
               "</table>"
    html += "</td></tr>"\
    "</table>"
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
