"""
Custom Attribute Rule Model View
"""
from wtforms import StringField
from application.modules.rule.views import RuleModelView


#pylint: disable=too-few-public-methods
class CustomAttributeView(RuleModelView):
    """
    Custom Attribute Model View
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        #pylint: disable=access-member-before-definition
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

