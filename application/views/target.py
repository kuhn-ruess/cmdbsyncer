"""
Target Model View
"""
from application.views.default import DefaultModelView

class TargetModelView(DefaultModelView):
    """
    Target Model
    """
    column_filters = (
       'name',
       'enabled',
    )
