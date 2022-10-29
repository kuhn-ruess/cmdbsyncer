"""
Default Model Views
"""
from flask import url_for, redirect
from flask_login import current_user
from flask_admin.contrib.mongoengine import ModelView
from flask_admin import AdminIndexView

class DefaultModelView(ModelView):
    """
    Default Model View Overwrite
    """

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated

class IndexView(AdminIndexView):
    """
    Index View Overwrite for auth
    """
    def is_visible(self):
        return False

    def is_accessible(self):
        return current_user.is_authenticated \
                and not current_user.force_password_change

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login', next=url_for('admin.index')))
