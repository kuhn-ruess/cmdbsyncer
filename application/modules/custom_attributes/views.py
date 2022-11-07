"""
Custom Attribute Rule Model View
"""
from flask_admin.contrib.mongoengine.filters import FilterEqual
from application.modules.rule.views import RuleModelView
from application.modules.custom_attributes.models import CustomAttributeRule


#pylint: disable=too-few-public-methods
class CustomAttributeView(RuleModelView):
    """
    Custom Attribute Model View
    """


    can_export = True

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        super().__init__(model, **kwargs)
