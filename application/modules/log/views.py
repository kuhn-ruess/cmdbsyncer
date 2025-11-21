"""
Log Model View
"""
from flask_login import current_user
from markupsafe import Markup
from application.views.default import DefaultModelView
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike

def format_log(v, c, m, p):
    """ Format Log view"""
    # pylint: disable=invalid-name, unused-argument
    html = "<table>"
    for entry in m.details:
        html += f"<tr><th>{entry.level}</th><td>{entry.message}</td></tr>"
    html += "</table>"
    return Markup(html)

def format_error_flag(v, c, m, p):
    """
    Format Has error flag"
    """
    # pylint: disable=invalid-name, unused-argument
    if m.has_error:
        return Markup('<span style="color:red;" class="fa fa-warning"></span>')
    return Markup('<span style="color:green;" class="fa fa-circle"></span>')


class LogView(DefaultModelView): #pylint: disable=too-few-public-methods
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
        'details': format_log,
        'has_error': format_error_flag,
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
