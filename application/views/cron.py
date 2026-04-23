"""
Cron Model View
"""
from datetime import datetime
from flask import flash
from flask_admin.actions import action
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike
from flask_login import current_user
from markupsafe import Markup, escape
from wtforms import HiddenField

from application.views.default import DefaultModelView

def format_error_flag(_v, _c, m, _p):
    """
    Format Has error flag"
    """
    if m.failure:
        return Markup('<span style="color:red;" class="fa fa-warning"></span>')
    return Markup('<span style="color:green;" class="fa fa-circle"></span>')


def format_date(_v, _c, m, p):
    """ Format Date Field"""
    if value := getattr(m, p):
        return datetime.strftime(value, "%d.%m.%Y %H:%M")
    return ""

def _render_interval(_view, _context, model, _name):
    """
    Render Interval
    """
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
        html += f"<tr><td>{idx}</td><td>{escape(entry['name'])}</td>"\
                f"<td>{escape(entry['command'])}</td><td>{escape(entry['account'])}</td></tr>"
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
        'continue_on_error',
        'webhook_enabled',
    ]

    column_formatters = {
        'render_jobs': _render_cronjob,
        'interval': _render_interval,
    }

    form_overrides = {
        'render_jobs': HiddenField,
    }

    form_widget_args = {
        'webhook_token': {
            'readonly': True,
            'placeholder': 'Generated automatically when Webhook is enabled.',
        },
    }

    def on_model_change(self, form, model, is_created):
        """Allocate a webhook token on first enable."""
        model.ensure_webhook_token()
        return super().on_model_change(form, model, is_created)

    @action('regenerate_webhook_token',
            'Regenerate Webhook Token',
            'Rotate the webhook token? Existing URLs using the old token '
            'will stop working immediately.')
    def action_regenerate_webhook_token(self, ids):
        """Rotate per-group webhook tokens for the selected groups."""
        from application.models.cron import CronGroup  # pylint: disable=import-outside-toplevel
        count = 0
        for group in CronGroup.objects(id__in=ids):
            group.regenerate_webhook_token()
            group.webhook_enabled = True
            group.save()
            count += 1
        flash(f'Webhook token regenerated for {count} group(s)', 'success')

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
        'last_success_at',
        'failure',
    )

    page_size = 50

    column_formatters = {
        'next_run': format_date,
        'last_run': format_date,
        'last_start': format_date,
        'last_ended': format_date,
        'last_success_at': format_date,
        'failure': format_error_flag,
    }
    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('cron')
