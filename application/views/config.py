"""
Models Config
"""
from flask_admin import expose
from flask_login import current_user
from application.views.default import DefaultModelView
from application.helpers.sates import remove_changes
from application.plugins.maintenance import clear_host_caches


class ConfigModelView(DefaultModelView):
    """
    Config View
    """
    page_size = 1
    can_delete = False
    can_create = False

    @expose('/commit_changes')
    def commit_changes(self):
        """
        Delete all Caches
        """
        remove_changes()
        clear_host_caches()
        return "Activation Done"

    def is_accessible(self):
        return current_user.is_authenticated and current_user.global_admin
