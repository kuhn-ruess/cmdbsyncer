"""
Folder Pool Model View
"""
from flask_login import current_user
from application.views.default import DefaultModelView

class FolderPoolModelView(DefaultModelView):
    """
    Account Model
    """
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
        return current_user.is_authenticated and current_user.has_right('rule')
