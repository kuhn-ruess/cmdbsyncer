"""
Folder Pool Model View
"""
from flask_login import current_user
from application.views.default import DefaultModelView

class FolderPoolModelView(DefaultModelView):
    """
    Account Model
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
        return current_user.is_authenticated and current_user.has_right('rule')

    def on_model_change(self, form, model, is_created):
        """
        Make Sure Folder are saved correct
        """

        if not  model.folder_name.startswith('/'):
            model.folder_name = "/" + model.folder_name

        return super().on_model_change(form, model, is_created)
