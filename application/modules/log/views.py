"""
Log Model View
"""
from html import escape
from markupsafe import Markup
from application.views.default import DefaultModelView
from flask_login import current_user


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

    column_filters = (
        'source', 'message',
    )
    page_size = 100

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated
