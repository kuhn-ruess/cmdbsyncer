"""
Cron Model View
"""
# pylint: disable=too-few-public-methods
from datetime import datetime
from flask_login import current_user
from markupsafe import Markup
from wtforms import HiddenField

from application.views.default import DefaultModelView


def format_date(v, c, m, p):
    """ Format Date Field"""
    if value := getattr(m,p):
        return datetime.strftime(value, "%d.%m.%Y %H:%M")

def _render_cronjob(_view, _context, model, _name):
    """
    Render BI Rule
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.jobs):
        html += f"<tr><td>{idx}</td><td>{entry['name']}</td>"\
                f"<td>{entry['command']}</td><td>{entry['account']}</td></tr>"
    html += "</table>"
    return Markup(html)

class CronGroupView(DefaultModelView):
    """
    Cron Group View
    """
    column_default_sort = "folder_name"

    column_exclude_list = [
        'jobs',
    ]


    column_filters = (
       'name',
       'enabled',
    )

    column_editable_list = [
        'enabled',
        'run_once_next',
    ]

    column_formatters = {
        'render_jobs': _render_cronjob,
    }

    form_overrides = {
        'render_jobs': HiddenField,
    }
    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('cron')



class CronStatsView(DefaultModelView):
    """
    Cron Stats Model
    """
    can_edit = True
    can_create = False
    can_export = True

    export_types = ['xlsx', 'csv']

    page_size = 50
    can_set_page_size = True

    column_formatters = {
        'next_run': format_date,
        'last_run': format_date,
        'last_start': format_date,
        'last_ended': format_date,
    }
    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('cron')
