"""
Rule Model View
"""
from wtforms import HiddenField, StringField
from flask_login import current_user
from flask_admin.form import rules
from markupsafe import Markup
from application.views.default import DefaultModelView
from application.modules.rule.models import filter_actions, rule_types

#   .-- Renderer
condition_types={
    'equal': "is equal",
    'in': "contains",
    'not_in': "not contains",
    'in_list': "found in list",
    'ewith': "endswith",
    'swith': "startswith",
    'regex': "regex match",
    'bool': "Boolean",
    'ignore': "always match",
}

div_open = rules.HTML('<div class="form-check form-check-inline">')
div_close = rules.HTML("</div>")

DIVIDER = '<div class="row"><div class="col"><hr></div>'\
          '<div class="col-auto">%s</div><div class="col"><hr></div></div>'


form_subdocuments_template = {
    'conditions': {
        'form_subdocuments' : {
            '': {
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
                    rules.HTML(DIVIDER % "Match on Host"),
                    rules.FieldSet(
                        ('hostname_match', 'hostname', 'hostname_match_negate'), "Host Match"),
                    rules.HTML(DIVIDER % "Match on Attribute"),
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

def _render_condition_typ(_view, _context, model, _name):
    """
    Render Condition Typ
    """
    translation = dict(rule_types)
    return translation[model.condition_typ]

def _render_filter_outcomes(_view, _context, model, _name):
    """
    Render Filter outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{dict(filter_actions)[entry.action]}</td>"
        if entry.attribute_name:
            html += f"<td><b>{entry.attribute_name}</b></td></tr>"
        else:
            html += "<td></td></tr>"

    html += "</table>"
    return Markup(html)


def _render_attribute_outcomes(_view, _context, model, _name):
    """
    Render attribute outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        html += f"<tr><td>{idx}</td><td>{entry.attribute_name}</td>"\
                f"<td><b>{entry.attribute_value}</b></td></tr>"
    html += "</table>"
    return Markup(html)


def _render_full_conditions(_view, _context, model, _name):
    """
    Render full condition set which contains host or labels
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.conditions):
        if entry.match_type == 'host':
            html += f"<tr><td>{idx}</td> <td><b>Hostname</b></td><td>"
            if entry.hostname_match_negate:
                html += "<b>NOT</b> "
            html += f"{condition_types[entry.hostname_match]}</td>"\
                    f"<td><b>{entry.hostname}</b></td></tr>"
        else:
            html += f"<tr><td>{idx}</td><td><b>Attribute</b></td><td>"\
                "<table width=100%>"\
                "<tr>"\
                "<td><b>Key</b></td>"\
                f"<td>{condition_types[entry.tag_match]}</td>"\
                f"<td><b>{entry.tag}</b></td>"\
                f"<td>Negate: <b>{entry.tag_match_negate}</b></td>"\
                "</tr>"\
                "<tr>"\
                "<td><b>Value</b></td>"\
                f"<td>{condition_types[entry.value_match]}</td>"\
                f"<td><b>{entry.value}</b></td>"\
                f"<td>Negate: <b>{entry.value_match_negate}</b></td>"\
                "</tr>"\
                "</table>"\
                "</td></tr>"
    html += "</table>"
    return Markup(html)

#.
#   .-- Rule Model
#pylint: disable=too-few-public-methods


class RuleModelView(DefaultModelView):
    """
    Rule Model
    """

    can_export = True

    export_types = ['xlsx', 'csv']

    form_rules = [
        rules.FieldSet((
            rules.Field('name'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            ), "1. Main Options"),
            div_close,
            rules.Field('sort_field'),
        rules.FieldSet(('condition_typ', 'conditions'), "2. Conditions"),
        rules.FieldSet(('outcomes', ), "3. Rule Outcomes"),
    ]

    form_widget_args = {
        #'enabled' : {'class': 'form-check-input'}
    }

    column_descriptions = {
        "last_match": 'No more rules match for objects matching this rule',
        "condition_typ": 'Either all Conditions, '\
                         'one condition or no condition need to match'\
                         'in order that the rule apply',
    }


    column_sortable_list = (
        'name',
        'enabled',
        'sort_field',
    )

    column_default_sort = ("sort_field", True), ("name", True)

    page_size = 300

    column_filters = (
       'name',
       'enabled',
    )

    column_editable_list = [
        'enabled',
    ]
    form_subdocuments = form_subdocuments_template

    column_formatters = {
        'render_full_conditions': _render_full_conditions,
        'render_attribute_outcomes': _render_attribute_outcomes,
        'condition_typ': _render_condition_typ,
    }

    form_overrides = {
        'name': StringField,
        'render_full_conditions': HiddenField,
        'render_attribute_outcomes': HiddenField,
    }

    column_labels = {
        'render_full_conditions': "Conditions",
        'render_attribute_outcomes': "New Attributes",
    }

    column_exclude_list = [
        'conditions', 'outcomes'
    ]



    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('rule')

#.
#   .-- Filter
#pylint: disable=too-few-public-methods
class FiltereModelView(DefaultModelView):
    """
    Filter
    """

    can_export = False


    form_subdocuments = form_subdocuments_template

    column_exclude_list = [
        'conditions', 'outcomes',
    ]

    column_default_sort = ("sort_field", True), ("name", True)


    page_size = 300

    column_filters = (
       'name',
       'enabled',
    )

    column_editable_list = [
        'enabled',
    ]

    column_formatters = {
        'render_full_conditions': _render_full_conditions,
        'render_filter_outcome': _render_filter_outcomes,
        'condition_typ': _render_condition_typ,
    }

    form_overrides = {
        'render_filter_outcome': HiddenField,
        'render_full_conditions': HiddenField,
    }

    column_labels = {
        'render_filter_outcome': "Filter Parameters",
        'render_full_conditions': "Conditions",
    }

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('rule')

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
                        }
                    },
                }
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)
#.
#   .-- Rewrite Attributes
def _render_attribute_rewrite(_view, _context, model, _name):
    """
    Render Attribute outcomes
    """
    html = "<table width=100%>"
    for idx, entry in enumerate(model.outcomes):
        attribute_name = entry.old_attribute_name
        html += f"<tr><td>{idx}</td>"
        colspan = 3
        value = entry.new_value
        if value:
            colspan = 0
        if not attribute_name:
            html += f"<td><b>New Attibute</b></td>"\
                    "<td><b>to</b></td>"\
                    f"<td>{entry.new_attribute_name}</td>"
        else:
            html += f"<td>{attribute_name}</td>"\
                    "<td><b>to</b></td>"\
                    f"<td colspan={colspan}>{entry.new_attribute_name}</td>"

        if value:
            html += f"<td><b>New Value</b></td><td>{value}</td>"
    html += "</tr></table>"
    return Markup(html)


#pylint: disable=too-few-public-methods
class RewriteAttributeView(RuleModelView):
    """
    Custom Attribute Model View
    """

    def __init__(self, model, **kwargs):
        """
        Update elements
        """
        self.column_formatters.update({
            'render_attribute_rewrite': _render_attribute_rewrite,
        })

        self.form_overrides.update({
            'render_attribute_rewrite': HiddenField,
        })

        self.column_labels.update({
            'render_attribute_rewrite': "Attribute Rewrites",
        })

        #pylint: disable=access-member-before-definition
        base_config = dict(self.form_subdocuments)
        base_config.update({
            'outcomes': {
                'form_subdocuments' : {
                    '': {
                        'form_overrides' : {
                            'old_attribute_name': StringField,
                            'new_attribute_name': StringField,
                            'new_value': StringField,
                        },
                        'form_widget_args': {
                            'old_attribute_name': {'style': 'background-color: #2EFE9A;' },
                            'overwrite_name': {'style': 'background-color: #2EFE9A;' },
                            'new_attribute_name': {'style': 'background-color: #2EFE9A;' },
                            'overwrite_value': { 'style': 'background-color: #81DAF5;' },
                            'new_value': { 'style': 'background-color: #81DAF5;' },
                        },
                    },
                },
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)
#.
