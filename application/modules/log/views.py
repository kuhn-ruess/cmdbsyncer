"""
Log Model View
"""
from html import escape
from markupsafe import Markup
from application.views.default import DefaultModelView
from flask_login import current_user

def _field_escape(_view, _context, model, name):
    """
    Show debug stuff
    """
    return Markup(escape(model[name]))

class LogView(DefaultModelView): #pylint: disable=too-few-public-methods
    """
    Log Model
    """

    can_edit = True
    can_delete = False
    can_create = False
    can_export = True

    export_types = ['csv', 'xlsx']

    column_filters = (
        'type', 'message', 'raw',
    )
    column_formatters = {
        'raw': _field_escape,
    }
    column_default_sort = ('id', True)
    page_size = 100

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated
