"""
Custom Attribute Rule Model View
"""
from flask_login import current_user
from wtforms import StringField
from application.modules.rule.views import RuleModelView


class CustomAttributeView(RuleModelView):
    """
    Custom Attribute Model View
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments' : {
                    '': {
                        'form_overrides' : {
                            'attribute_name': StringField,
                            'attribute_value': StringField,
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('global_attributes')
