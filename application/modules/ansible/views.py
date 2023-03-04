"""
Ansible Rule Views
"""
from application.modules.rule.views import RuleModelView, divider
from flask_admin.form import rules
from wtforms import StringField


#pylint: disable=too-few-public-methods
class AnsibleCustomVariablesView(RuleModelView):
    """
    Custom Rule Model View
    """

    #@TODO: Fix that it's not possible just to reference to from_subdocuments_template
    form_subdocuments = {
        'conditions': {
            'form_subdocuments' : {
                None: {
                    'form_widget_args': {
                        'hostname_match': {'style': 'background-color: #2EFE9A;' },
                        'hostname': { 'style': 'background-color: #2EFE9A;', 'size': 50},
                        'tag_match': { 'style': 'background-color: #81DAF5;' },
                        'tag': { 'style': 'background-color: #81DAF5;' },
                        'value_match': { 'style': 'background-color: #81DAF5;' },
                        'value': { 'style': 'background-color: #81DAF5;'},
                    },
                    'form_overrides' : {
                        'hostname': StringField,
                        'tag': StringField,
                        'value': StringField,
                    },
                    'form_rules' : [
                        rules.FieldSet(('match_type',), "Condition Match Type"),
                        rules.HTML(divider % "Match on Host"),
                        rules.FieldSet(
                            ('hostname_match', 'hostname', 'hostname_match_negate'), "Host Match"),
                        rules.HTML(divider % "Match on Attribute"),
                        rules.FieldSet(
                            (
                                'tag_match', 'tag', 'tag_match_negate',
                                'value_match', 'value', 'value_match_negate',
                            ), "Attribute Match"),
                    ]
                }
            }
        }
    }


