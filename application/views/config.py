"""
Models Config
"""
#pylint: disable=no-member
#pylint: disable=missing-function-docstring
#pylint: disable=no-self-use
from application.views.default import DefaultModelView
from flask_login import current_user


class ConfigModelView(DefaultModelView):
    """
    Config View
    """
    page_size = 1
    can_delete = False
    can_create = False

    def is_accessible(self):
        return current_user.is_authenticated and current_user.global_admin
