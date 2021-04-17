"""
Account Model View
"""
from application.views.default import DefaultModelView

class AccountModelView(DefaultModelView):
    """
    Account Model
    """
    column_filters = (
       'name',
       'enabled',
    )
