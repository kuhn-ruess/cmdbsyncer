"""
Log Model View
"""
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike
from flask_login import current_user
from markupsafe import Markup, escape

from application.views.default import DefaultModelView

def format_log(_view, _ctx, model, _path):
    """Render the details list as a table that wraps long values.

    The key column shrinks to its widest token (``width:1%`` + ``nowrap``);
    the value column takes everything else and breaks on word boundaries
    so long URLs / stack lines stay inside the row.
    """
    rows = ''.join(
        '<tr>'
        '<th style="width:1%;vertical-align:top;padding:2px 8px 2px 0;'
        f'white-space:nowrap;color:#666;font-weight:600;">{escape(entry.level)}</th>'
        '<td style="vertical-align:top;word-break:break-word;'
        f'overflow-wrap:anywhere;white-space:pre-wrap;">{escape(entry.message)}</td>'
        '</tr>'
        for entry in model.details
    )
    return Markup(
        '<table style="width:100%;max-width:100%;border-collapse:collapse;">'
        f'{rows}'
        '</table>'
    )


def format_traceback(_view, _ctx, model, _path):
    """
    Tracebacks are routinely 30-80 lines and would otherwise blow up the
    detail card. Render them inside a collapsed `<details>` so the row
    stays scannable and the operator can pop it open on click.
    """
    trace = (model.traceback or '').strip()
    if not trace or trace == 'NoneType: None':
        return ''
    return Markup(
        '<details style="margin:0;">'
        '<summary style="cursor:pointer;color:#2c5d99;'
        'font-family:ui-monospace,monospace;font-size:0.88rem;">'
        'Show traceback</summary>'
        '<pre style="margin-top:6px;padding:8px 10px;'
        'background:#f6f8fa;border:1px solid #e2e6ea;border-radius:6px;'
        'font-size:0.82rem;white-space:pre-wrap;'
        f'overflow-x:auto;">{escape(trace)}</pre>'
        '</details>'
    )


def format_error_flag(_view, _ctx, model, _path):
    """Render the has_error flag as a coloured icon."""
    if model.has_error:
        return Markup('<span style="color:red;" class="fa fa-warning"></span>')
    return Markup('<span style="color:green;" class="fa fa-circle"></span>')


def format_message(_view, _ctx, model, _path):
    """
    Cap the message column width so the details column gets the lion's
    share of the row, but keep a 150px floor so short messages still
    have room to breathe.
    """
    return Markup(
        '<div style="min-width:150px;max-width:42ch;word-break:break-word;'
        f'overflow-wrap:anywhere;">{escape(model.message or "")}</div>'
    )


class LogView(DefaultModelView):
    """
    Log Model
    """

    can_edit = False
    can_delete = False
    can_create = False
    can_export = True
    can_view_details = True

    export_types = ['csv']

    column_extra_row_actions = [] # Overwrite because of clone icon

    column_details_list = [
        'datetime', 'message', 'details', 'has_error', 'source', 'traceback',
    ]

    column_default_sort = ('id', True)

    column_sortable_list = (
        'datetime',
        'message',
        'has_error'
    )

    column_formatters = {
        'message': format_message,
        'details': format_log,
        'has_error': format_error_flag,
        'traceback': format_traceback,
    }

    column_filters = (
       FilterLike(
            "source",
           'Error Source'
       ),
       FilterLike(
            "message",
           'Message'
       ),
       FilterLike(
            "affected_hosts",
           'Hosts Affected'
       ),
       BooleanEqualFilter(
            "has_error",
           'Entries with Error'
       )
    )
    page_size = 100

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('log')
