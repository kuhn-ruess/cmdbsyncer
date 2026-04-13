"""
Vmware Rule Views
"""
from flask_login import current_user
from application.modules.rule.views import RuleModelView


class VMwareCustomAttributeView(RuleModelView):
    """
    Custom Rule Model View
    """

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('vmware')
