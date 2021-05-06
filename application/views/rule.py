"""
Rule Model View
"""
from application.views.default import DefaultModelView

class RuleModelView(DefaultModelView):
    """
    Rule Model
    """
    column_filters = (
       'name',
       'enabled',
    )
