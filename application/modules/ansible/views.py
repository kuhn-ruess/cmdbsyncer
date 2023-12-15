"""
Ansible Rule Views
"""
from application.modules.rule.views import RuleModelView

#pylint: disable=too-few-public-methods
class AnsibleCustomVariablesView(RuleModelView):
    """
    Custom Rule Model View
    """

    can_export = False

    column_exclude_list = [
        'conditions', 'outcomes',
    ]
