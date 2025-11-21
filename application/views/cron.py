"""
Cron Model View
"""
# pylint: disable=too-few-public-methods
from datetime import datetime
from flask_login import current_user
from markupsafe import Markup
from wtforms import HiddenField
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike

from application.views.default import DefaultModelView

def format_error_flag(v, c, m, p):
    """
    Format Has error flag"
    """
    # pylint: disable=invalid-name, unused-argument
    if m.failure:
        return Markup('<span style="color:red;" class="fa fa-warning"></span>')
    return Markup('<span style="color:green;" class="fa fa-circle"></span>')


def format_date(v, c, m, p):
    """ Format Date Field"""
    if value := getattr(m,p):
        return datetime.strftime(value, "%d.%m.%Y %H:%M")

def _render_interval(_view, _context, model, _name):
    """
    Render Interval
    """
    # pylint: disable=unused-argument
    if model.interval == '10min':
        return "15 Minutes"
    if model.interval == 'hour':
        return "Hourly"
    if model.interval == 'daily':
        return "Daily"
    return "Unknown"

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

    column_exclude_list = [
        'jobs',
    ]


    column_default_sort = ("sort_field", False)

    column_sortable_list = (
        'name',
        'sort_field',
        'timerange_from',
        'timerange_to',
        'interval',
        'enabled'
    )

    column_labels = {
        'render_jobs': "Cronjobs",
    }

    column_filters = (
       FilterLike(
            "name",
           'Name'
       ),
       BooleanEqualFilter(
            "enabled",
           'Enabled'
       )
    )

    column_editable_list = [
        'enabled',
        'run_once_next',
    ]

    column_formatters = {
        'render_jobs': _render_cronjob,
        'interval': _render_interval,
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
    can_edit = False
    can_create = False
    can_export = True

    column_extra_row_actions = [] # Overwrite because of clone icon

    export_types = ['xlsx', 'csv']

    column_default_sort = ("group", True), ("next_run", True)

    column_sortable_list = (
        'group',
        'next_run',
        'last_start',
        'last_ended',
        'failure',
    )

    page_size = 50

    column_formatters = {
        'next_run': format_date,
        'last_run': format_date,
        'last_start': format_date,
        'last_ended': format_date,
        'failure': format_error_flag,
    }
    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('cron')
