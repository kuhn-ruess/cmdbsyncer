"""
Ansible Rule Views
"""
from flask_login import current_user
from application.modules.rule.views import RuleModelView

#pylint: disable=too-few-public-methods
class AnsibleCustomVariablesView(RuleModelView):
    """
    Custom Rule Model View
    """


    column_exclude_list = [
        'conditions', 'outcomes',
    ]

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('ansible')

