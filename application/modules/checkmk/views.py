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
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{entry.group_name}</td>"\
                f"<td>{entry.foreach_type}</td>" \
                f"<td>{entry.foreach}</td>" \
                f"<td>{entry.regex}</td>" \
                "</tr>"
    html += "</table>"
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
