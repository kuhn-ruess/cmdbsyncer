from flask_login import current_user
from flask_admin.contrib.fileadmin import FileAdmin


class FileAdminView(FileAdmin):
    """
    Fileadmin Settings
    """


    can_rename = True
    rename_modal = True
    upload_modal = True

    mkdir_modal = True
    edit_modal = True


    allowed_extensions = ('md', 'txt', 'csv', 'yml', 'json', 'pem', 'cert')
    editable_extensions = ('md', 'txt', 'csv', 'yml', 'json', 'pem')

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('fileadmin')
