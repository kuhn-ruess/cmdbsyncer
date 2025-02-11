"""
Vmware Rule Views
"""
from datetime import datetime
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DjangoLexer

from markupsafe import Markup
from wtforms import HiddenField, StringField

from application.views.default import DefaultModelView
from application.modules.rule.views import RuleModelView, get_rule_json


#pylint: disable=too-few-public-methods
class VMwareCustomAttributeView(RuleModelView):
    """
    Custom Rule Model View
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """

        #self.column_formatters.update({
        #    'render_attribute_outcomes': _render_netbox_outcome
        #})

        #self.form_overrides.update({
        #    'render_attribute_outcomes': HiddenField,
        #})

        #self.column_labels.update({
        #    'render_attribute_outcomes': "Custom Attributes",
        #})
        #pylint: disable=access-member-before-definition
        #base_config = dict(self.form_subdocuments)
        #base_config.update({
        #    'outcomes': {
        #        'form_subdocuments' : {
        #            '': {
        #                'form_widget_args': {
        #                    'param' : {"rows": 10},
        #                },
        #                'form_overrides' : {
        #                    #'param': StringField,
        #                }
        #            },
        #        }
        #    }
        #})
        #self.form_subdocuments = base_config

        super().__init__(model, **kwargs)
