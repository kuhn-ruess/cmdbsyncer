"""
Rule Model View
"""
from datetime import datetime

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DjangoLexer

from wtforms import HiddenField, StringField
from flask_login import current_user
from flask_admin.form import rules
from markupsafe import Markup
from application.views.default import DefaultModelView
from application.modules.rule.models import filter_actions, rule_types, condition_types
from application.docu_links import docu_links
from application.helpers.sates import add_changes


#   .-- Renderer
condition_types={
    'equal': "is equal",
    'in': "contains",
    'not_in': "not contains",
    'in_list': "found in given list",
    'string_in_list': "found in list",
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
                    rules.Field('match_type',),
                    rules.HTML("<div class='form-row'><div class='col host'>"),
                    rules.FieldSet(
                        ('hostname_match', 'hostname', 'hostname_match_negate'),
                         "Match for Hostname"),
                    rules.HTML("</div><div class='col tag'>"),

                    rules.FieldSet(
                        (
                            'tag_match', 'tag', 'tag_match_negate',
                            'value_match', 'value', 'value_match_negate',
                        ), "Match for Attribute"),
                    rules.HTML("</div></div>"),
                ]
            }
        }
    }
}

def _render_jinja(_view, _context, model, name):
    """
    Render A field containing a Jinja Tempalte
    """
    value = highlight(model[name], DjangoLexer(),
              HtmlFormatter(sytle='colorfull'))
    return Markup(f'{value}')

def _render_condition_typ(_view, _context, model, _name):
    """
    Render Condition Typ
    """
    badges = {
            'all': 'success',
            'any': 'warning',
            'anyway': 'danger',
    }
    badge = badges[model.condition_typ]

    rule_names = dict(rule_types)
    translation = rule_names[model.condition_typ]
    return Markup(f'<span class="badge badge-{badge}">{translation}<span>')

def _render_filter_outcomes(_view, _context, model, _name):
    """
    Render Filter outcomes
    """
    html = ""
    for entry in model.outcomes:
        action = dict(filter_actions)[entry.action]
        value = ""
        if entry.attribute_name:
            value = \
                highlight(entry.attribute_name, DjangoLexer(),
                          HtmlFormatter(sytle='colorfull'))
        html += f'''
            <div class="card">
              <div class="card-body">
                <h6 class="card-subtitle mb-2 text-muted">{action}</h6>
                <p class="card-text">
                 {value}
                </p>
              </div>
            </div>
            '''
    return Markup(html)


def _render_attribute_outcomes(_view, _context, model, _name):
    """
    Render attribute outcomes
    """
    html = ""
    for entry in model.outcomes:
        html += f'''
            <div class="card">
              <div class="card-body">
                <p class="card-text">
                 <span class="badge badge-primary">
                 {entry.attribute_name}</span><b>:</b><span class="badge badge-info">
                {entry.attribute_value}
                </span>
                </p>
              </div>
            </div>
            '''
    return Markup(html)


def _render_full_conditions(_view, _context, model, _name):
    """
    Render full condition set which contains host or labels
    """
    negate = {
        True: 'not ',
        False: ' ',
    }
    html = ""
    for entry in model.conditions:
        if entry.match_type == 'host':
            html += f'''
                <div class="card">
                  <div class="card-body">
                    <h6 class="card-subtitle mb-2 text-muted">Hostname</h6>
                    <p class="card-text">
                     <span class="badge badge-primary">
                     {negate[entry.hostname_match_negate]}
                     {condition_types[entry.hostname_match]}</span>
                    <span class="badge badge-info">{entry.hostname}</span>
                    </p>
                  </div>
                </div>
                '''
        else:
            html += f'''
                <div class="card">
                  <div class="card-body">
                    <h6 class="card-subtitle mb-2 text-muted">Key</h6>
                    <p class="card-text">
                     <span class="badge badge-primary">
                        {negate[entry.tag_match_negate]}{condition_types[entry.tag_match]}
                     </span>
                     <span class="badge badge-info">{entry.tag}</span>
                    </p>
                    <h6 class="card-subtitle mb-2 text-muted">Value</h6>
                    <p class="card-text">
                    <span class="badge badge-primary">
                        {negate[entry.value_match_negate]} {condition_types[entry.value_match]}
                    </span>
                    <span class="badge badge-info">{entry.value}</span>
                    </p>
                  </div>
                </div>
                '''
    return Markup(html)

#.
#   .-- Rule Model
#pylint: disable=too-few-public-methods

def get_rule_json(_view, _context, model, _name):
    """
    Export Given Rulesets, Cant be imported from views
    So its duplicate
    """
    return model.to_json()

class RuleModelView(DefaultModelView):
    """
    Rule Model
    """

    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }

    form_rules = [
        rules.FieldSet((
            rules.Field('name'),
            rules.Field('documentation'),
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

    column_default_sort = ("sort_field", False)

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

    def on_model_change(self, form, model, is_created):
        """
        Overwrite Actions on Model Change
        """
        add_changes()

        return super().on_model_change(form, model, is_created)

    def on_model_delete(self, model):
        """
        Overwrite Actions on Model Delete
        """
        add_changes()

        return super().on_model_delete(model)

    def get_export_name(self, export_type):
        """
        Overwrite Filename
        """
        now = datetime.now()

        dt_str = now.strftime("%Y%m%d%H%M")
        return f"{self.model.__name__}_{dt_str}.syncer_json"


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

    can_export = True

    export_types = ['syncer_rules', ]

    column_export_list = ('name', )

    column_formatters_export = {
        'name': get_rule_json
    }


    form_subdocuments = form_subdocuments_template

    form_rules = [
        rules.FieldSet((
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            ), "1. Main Options"),
            div_close,
            rules.Field('sort_field'),

       rules.FieldSet(
           ( 'condition_typ', 'conditions',
           ), "2. Conditions"),
       rules.FieldSet(
           ( 'outcomes',
           ), "3. Filter"),
    ]

    column_exclude_list = [
        'conditions', 'outcomes',
    ]

    column_default_sort = ("sort_field", True), ("name", True)

    column_sortable_list = (
        'name',
        'sort_field',
        'enabled',
    )

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

    def get_export_name(self, export_type):
        """
        Overwrite Filename
        """
        now = datetime.now()

        dt_str = now.strftime("%Y%m%d%H%M")
        return f"{self.model.__name__}_{dt_str}.syncer_json"

    def is_accessible(self):
        """ Overwrite """
        return current_user.is_authenticated and current_user.has_right('rule')

    def on_model_change(self, form, model, is_created):
        """
        Overwrite Actions on Model Change
        """
        add_changes()

        return super().on_model_change(form, model, is_created)

    def on_model_delete(self, model):
        """
        Overwrite Actions on Model Delete
        """
        add_changes()

        return super().on_model_delete(model)

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
    html = ""
    for entry in model.outcomes:
        old_attr_name = entry.old_attribute_name
        new_attr_name  = entry.new_attribute_name

        value = \
            highlight(entry.new_value, DjangoLexer(), HtmlFormatter(sytle='colorfull'))

        if old_attr_name and new_attr_name:
            attribute_name = f"Rewrite from {old_attr_name} to {new_attr_name}"
        elif old_attr_name:
            attribute_name = old_attr_name
        else:
            attribute_name = new_attr_name

        html += f'''
            <div class="card">
              <div class="card-body">
                <h6 class="card-subtitle mb-2 text-muted">New Attribute</h6>
                <p class="card-text">
                {attribute_name}
                </p>
                <h6 class="card-subtitle mb-2 text-muted">To new Value</h6>
                {value}
              </div>
            </div>
            '''
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
                        'form_args': {
                            'overwrite_name': {'label': 'Operation'},
                            'overwrite_value': {'label': 'Operation'},
                        },
                        'form_overrides' : {
                            'old_attribute_name': StringField,
                            'new_attribute_name': StringField,
                        },
                        'form_widget_args': {
                            'overwrite_name': {'style': 'background-color: #2EFE9A;' },
                            'old_attribute_name': {'style': 'background-color: #2EFE9A;' },
                            'new_attribute_name': {'style': 'background-color: #2EFE9A;' },
                            'overwrite_value': { 'style': 'background-color: #81DAF5;' },
                            'new_value': { 'style': 'background-color: #81DAF5;' },
                        },
                        'form_rules' : [
                            rules.HTML(f'<i class="fa fa-info"></i><a href="{docu_links["rewrite"]}"'\
                                        'target="_blank" class="badge badge-light">Documentation</a>'),
                            rules.HTML("<div class='form-row'><div class='col'>"),
                            rules.FieldSet(
                                ('overwrite_name', 'old_attribute_name','new_attribute_name'),
                                 "Attribute Name"),
                            rules.HTML("</div><div class='col tag'>"),
                            rules.FieldSet(
                                ( 'overwrite_value', 'new_value'
                                ), "Attribute Value"),
                            rules.HTML("</div></div>"),
                        ]
                    },
                },
            }
        })
        self.form_subdocuments = base_config

        super().__init__(model, **kwargs)
#.
