"""
Models Config
"""
#pylint: disable=no-member
#pylint: disable=missing-function-docstring
from application import app
from application.models.host import Host
from application.views.default import DefaultModelView
from application.helpers.sates import remove_changes
from flask import flash, redirect
from flask_admin import expose
from flask_login import current_user


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
        Host.objects(cache__ne={}).update(set__cache={})
        return "Activation Done"

    def is_accessible(self):
        return current_user.is_authenticated and current_user.global_admin
