"""
Rule Model View
"""
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
