"""
Rule Model View
"""
from flask_login import current_user
from application.views.default import DefaultModelView

class RuleModelView(DefaultModelView):
    """
    Rule Model
    """
    column_default_sort = "sort_field"
    column_filters = (
       'name',
       'enabled',
    )

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('rule')
