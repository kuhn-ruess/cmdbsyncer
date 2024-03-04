"""
Log Model View
"""
from flask_login import current_user
from markupsafe import Markup
from application.views.default import DefaultModelView

def format_log(v, c, m, p):
    """ Format Log view"""
    # pylint: disable=invalid-name, unused-argument
    html = "<table>"
    for entry in m.details:
        html += f"<tr><th>{entry.level}</th><td>{entry.message}</td></tr>"
    html += "</table>"
    return Markup(html)


class LogView(DefaultModelView): #pylint: disable=too-few-public-methods
    """
    Log Model
    """

    can_edit = False
    can_delete = False
    can_create = False
    can_export = True
    can_view_details = True

    export_types = ['csv', 'xlsx']

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
    }

    column_filters = (
        'source', 'message',
    )
    page_size = 100

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated
