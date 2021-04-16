"""
Source Model View
"""
from application.views.default import DefaultModelView

class SourceModelView(DefaultModelView):
    """
    Source Model
    """
    column_filters = (
       'name',
       'enabled',
    )
