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
    form_subdocuments = {
        'conditions': {
            'form_subdocuments' : {
                None: {
                    'form_widget_args': {
                        'hostname_match': { 'style': 'background-color: #2EFE9A' },
                        'hostname': { 'style': 'background-color: #2EFE9A' },
                        'tag_match': { 'style': 'background-color: #81DAF5' },
                        'tag': { 'style': 'background-color: #81DAF5' },
                        'value_match': { 'style': 'background-color: #81DAF5' },
                        'value': { 'style': 'background-color: #81DAF5' },
                    },
                }
            }
        }
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('rule')
