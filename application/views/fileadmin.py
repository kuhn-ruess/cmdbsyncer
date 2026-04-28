"""Fileadmin view with audit hooks for file/directory mutations."""
import os

from flask_login import current_user
from flask_admin.contrib.fileadmin import FileAdmin

from application.helpers.audit import audit


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


    # Define the columns to show
    possible_columns = ('name', 'rel_path')
    column_list = ('name', 'size', 'date')

    list_template = 'admin/file/list.html'

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('fileadmin')

    # ------------------------------------------------------------------
    # Audit hooks
    #
    # Flask-Admin's FileAdmin doesn't go through MongoEngine, so the
    # signal-based audit recorder never sees these mutations. We emit
    # explicit `file.*` / `directory.*` events from the on_* hooks so
    # the audit log captures who edited which file when. `audit()` is a
    # no-op on community installs, so this stays free for OSS users.
    # ------------------------------------------------------------------

    @staticmethod
    def _file_size(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return None

    def on_file_upload(self, directory, path, filename):
        audit('file.uploaded',
              target_type='File', target_name=filename,
              metadata={'path': path,
                        'directory': str(directory),
                        'size': self._file_size(os.path.join(str(directory),
                                                             filename))})

    def on_edit_file(self, full_path, path):
        audit('file.edited',
              target_type='File', target_name=path,
              metadata={'full_path': full_path,
                        'size': self._file_size(full_path)})

    def on_rename(self, full_path, dir_base, filename):
        audit('file.renamed',
              target_type='File', target_name=filename,
              metadata={'from': full_path,
                        'to': os.path.join(str(dir_base), filename)})

    def on_file_delete(self, full_path, filename):
        audit('file.deleted',
              target_type='File', target_name=filename,
              metadata={'full_path': full_path})

    def on_mkdir(self, parent_dir, dir_name):
        audit('directory.created',
              target_type='Directory', target_name=dir_name,
              metadata={'parent_dir': parent_dir})

    def on_directory_delete(self, full_path, dir_name):
        audit('directory.deleted',
              target_type='Directory', target_name=dir_name,
              metadata={'full_path': full_path})
