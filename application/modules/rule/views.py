"""
Rule Model View
"""
# pylint: disable=line-too-long,trailing-whitespace,no-name-in-module
# pylint: disable=duplicate-code
# pylint: disable=wrong-import-order,ungrouped-imports,signature-differs
from datetime import datetime
from mongoengine.errors import NotUniqueError


from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DjangoLexer
from flask import flash

from wtforms import HiddenField, StringField
from flask_login import current_user
from flask_admin.form import rules
from markupsafe import Markup, escape
from application.views.default import DefaultModelView
from application.modules.rule.models import filter_actions, rule_types, condition_types
from application.docu_links import docu_links
from application.helpers.sates import add_changes
from flask_admin.contrib.mongoengine.filters import BooleanEqualFilter, FilterLike



#   .-- Renderer
condition_types={
    'equal': "exact match",
    'in': "contains",
    'not_in': "not contains", 
    'in_list': "value in your list",
    'string_in_list': "string in Python list",
    'ewith': "ends with",
    'swith': "starts with",
    'regex': "regex match",
    'bool': "boolean match",
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
                    'hostname_match': {
                        'style': (
                            'background-color: #2EFE9A; '
                            'border-radius: 5px; '
                            'padding: 6px 10px; '
                            'border: 1px solid #1abc9c; '
                            'width: 900px;'
                        )
                    },
                    'hostname': {
                        'style': (
                            'background-color: #2EFE9A; '
                            'border-radius: 5px; '
                            'padding: 6px 10px; '
                            'font-weight: bold; '
                            'border: 1px solid #1abc9c; '
                            'width: 300px;'
                        ),
                        'size': 35
                    },
                    'tag_match': {
                        'style': (
                            'background-color: #81DAF5; '
                            'border-radius: 5px; '
                            'padding: 6px 10px; '
                            'border: 1px solid #3498db; '
                            'width: 900px;'
                        )
                    },
                    'tag': {
                        'style': (
                            'background-color: #81DAF5; '
                            'border-radius: 5px; '
                            'padding: 6px 10px; '
                            'font-family: monospace; '
                            'border: 1px solid #3498db; '
                            'width: 300px;'
                        )
                    },
                    'value_match': {
                        'style': (
                            'background-color: #81DAF5; '
                            'border-radius: 5px; '
                            'padding: 6px 10px; '
                            'border: 1px solid #3498db; '
                            'width: 900px;'
                        )
                    },
                    'value': {
                        'style': (
                            'background-color: #81DAF5; '
                            'border-radius: 5px; '
                            'padding: 6px 10px; '
                            'font-family: monospace; '
                            'border: 1px solid #3498db; '
                            'width: 300px;'
                        )
                    },
                    'match_type': {'class': 'cond-match-type'},
                },
                'form_overrides' : {
                    'hostname': StringField,
                    'tag': StringField,
                    'value': StringField,
                },
                'form_rules' : [
                    rules.HTML("<div class='condition'>"),
                    rules.HTML('<button type="button" value="host" class="btn btn-info btnCondition">Match by Hostname</button>'),
                    rules.HTML('<button type="button" value="attr" class="btn btn-info btnCondition">Match by Attribute</button>'),
                    rules.HTML('<hr>'),
                    rules.HTML('<div class="hidden">'),
                    rules.Field('match_type',),
                    rules.HTML('</div>'),

                    rules.HTML("<div class='cond-host'>"),
                    rules.HTML("<div class='form-row mb-2'>"),
                    rules.HTML("<div class='col-auto'>"),
                    rules.Field('hostname'),
                    rules.HTML("</div>"),
                    rules.HTML("<div class='col-auto'>"),
                    rules.Field('hostname_match'),
                    rules.HTML("</div>"),
                    rules.HTML("</div>"),
                    
                    rules.HTML("<div class='form-row mb-3'>"),
                    rules.HTML("<div class='col-auto'>"),
                    rules.Field('hostname_match_negate'),
                    rules.HTML("</div>"),
                    rules.HTML("</div>"),
                    
                    rules.HTML("</div><div class='cond-attr' style='display: none;'>"),

                    rules.HTML("<div class='form-row mb-2'>"),
                    rules.HTML("<div class='col-auto'>"),
                    rules.Field('tag'),
                    rules.HTML("</div>"),
                    rules.HTML("<div class='col-auto'>"),
                    rules.Field('tag_match'),
                    rules.HTML("</div>"),
                    rules.HTML("</div>"),
                    
                    rules.HTML("<div class='form-row mb-3'>"),
                    rules.HTML("<div class='col-auto'>"),
                    rules.Field('tag_match_negate'),
                    rules.HTML("</div>"),
                    rules.HTML("</div>"),
                    
                    rules.HTML("<div class='form-row mb-2'>"),
                    rules.HTML("<div class='col-auto'>"),
                    rules.Field('value'),
                    rules.HTML("</div>"),
                    rules.HTML("<div class='col-auto'>"),
                    rules.Field('value_match'),
                    rules.HTML("</div>"),
                    rules.HTML("</div>"),
                    
                    rules.HTML("<div class='form-row'>"),
                    rules.HTML("<div class='col-auto'>"),
                    rules.Field('value_match_negate'),
                    rules.HTML("</div>"),
                    rules.HTML("</div>"),
                    
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
    value = highlight(str(model[name]), DjangoLexer(),
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
    return Markup(f'<span class="badge badge-{escape(badge)}">{escape(translation)}</span>')

def _render_filter_outcomes(_view, _context, model, _name):
    """
    Render Filter outcomes
    """
    html = ""
    for entry in model.outcomes:
        action = escape(dict(filter_actions)[entry.action])
        value = ""
        if entry.attribute_name:
            value = \
                highlight(str(entry.attribute_name), DjangoLexer(),
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
                 {escape(entry.attribute_name)}</span><b>:</b><span class="badge badge-info">
                {escape(entry.attribute_value)}
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
                     {escape(negate[entry.hostname_match_negate])}
                     {escape(condition_types[entry.hostname_match])}</span>
                    <span class="badge badge-info">{escape(entry.hostname)}</span>
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
                        {escape(negate[entry.tag_match_negate])}{escape(condition_types[entry.tag_match])}
                     </span>
                     <span class="badge badge-info">{escape(entry.tag)}</span>
                    </p>
                    <h6 class="card-subtitle mb-2 text-muted">Value</h6>
                    <p class="card-text">
                    <span class="badge badge-primary">
                        {escape(negate[entry.value_match_negate])} {escape(condition_types[entry.value_match])}
                    </span>
                    <span class="badge badge-info">{escape(entry.value)}</span>
                    </p>
                  </div>
                </div>
                '''
    return Markup(html)

#.
#   .-- Rule Model

def get_rule_json(_view, _context, model, _name):
    """
    Export Given Rulesets, Cant be imported from views
    So its duplicate
    """
    return model.to_json()


# --- Modern rule-form styling ---------------------------------------------
# Every rule form across all systems (Checkmk, Netbox, Ansible, Idoit,
# VMware, Custom Attributes, etc.) follows the same 3-step layout:
# Main Options → Conditions → Outcomes. The helpers below produce a
# consistent card-per-step visual so the forms don't feel like raw
# Flask-Admin scaffolds.

_MODERN_RULE_CSS = '''
<style>
.rule-form-sections { display: flex; flex-direction: column; gap: 14px;
    margin: 8px 0 16px; }
.rule-section { border: 1px solid #e2e6ea; border-radius: 10px;
    background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    overflow: hidden; }
.rule-section-head { display: flex; align-items: center; gap: 12px;
    padding: 10px 14px; border-bottom: 1px solid #eef0f3;
    background: #f8f9fa; }
.rule-section-head .rule-step { flex: 0 0 auto; display: inline-flex;
    align-items: center; justify-content: center; width: 28px; height: 28px;
    border-radius: 50%; font-weight: bold; color: #fff; font-size: 0.9rem;
    font-family: ui-monospace, monospace; }
.rule-section-head h4 { margin: 0; font-size: 1.05rem; color: #2c3e50; }
.rule-section-head p { margin: 0; font-size: 0.82rem; color: #6c757d; }
.rule-section-body { padding: 12px 14px; }
.rule-section-body > .form-group:last-child { margin-bottom: 0; }

.rule-section-main   { border-left: 4px solid #3498db; }
.rule-section-main   .rule-step { background: #3498db; }
.rule-section-cond   { border-left: 4px solid #e67e22; }
.rule-section-cond   .rule-step { background: #e67e22; }
.rule-section-out    { border-left: 4px solid #27ae60; }
.rule-section-out    .rule-step { background: #27ae60; }

/* Tighten up FieldList cards Flask-Admin renders for conditions /
   outcomes: hide the "Conditions #N" legend text, keep the delete X,
   and make each inline card look like a sub-card nested inside the
   outer step card rather than another card with its own shadow. */
[id^="conditions-"] > legend,
[id^="outcomes-"] > legend,
[id^="rewrite_attributes-"] > legend { display: none !important; }
[id^="conditions-"] .inline-field > legend > small,
[id^="outcomes-"] .inline-field > legend > small,
[id^="rewrite_attributes-"] .inline-field > legend > small {
    font-size: 0 !important;
}
[id^="conditions-"] .inline-field > legend > small .pull-right,
[id^="outcomes-"] .inline-field > legend > small .pull-right,
[id^="rewrite_attributes-"] .inline-field > legend > small .pull-right {
    font-size: 1rem !important;
}
[id^="conditions-"] .inline-field.card,
[id^="outcomes-"] .inline-field.card,
[id^="rewrite_attributes-"] .inline-field.card {
    border: 1px solid #e6e9ec !important;
    background: #fbfcfd !important;
    border-radius: 8px !important;
    box-shadow: none !important;
    padding: 10px 12px !important;
    margin-bottom: 10px !important;
    position: relative;
}
[id^="conditions-"] .inline-field.card > legend,
[id^="outcomes-"] .inline-field.card > legend,
[id^="rewrite_attributes-"] .inline-field.card > legend {
    position: absolute !important; top: 4px; right: 6px;
    padding: 0 !important; margin: 0 !important; border: none !important;
    width: auto !important;
}
[id^="conditions-"] .form-group,
[id^="outcomes-"] .form-group,
[id^="rewrite_attributes-"] .form-group { margin-bottom: 6px !important; }
/* The big "Add Conditions" / "Add Outcomes" buttons at the bottom of
   the field list carry the default flask-admin `btn btn-primary`
   style — soften them so they don't shout louder than the actual
   Save button in the page footer. */
[id^="conditions-"] > a.btn,
[id^="outcomes-"] > a.btn,
[id^="rewrite_attributes-"] > a.btn {
    background: #f8f9fa !important; border: 1px solid #ced4da !important;
    color: #2c3e50 !important; font-size: 0.88rem !important;
    padding: 4px 12px !important;
}
</style>
'''


def _rule_section_open(step, kind, title, desc):
    """Emit a `rules.HTML` that opens a rule-form step card."""
    return rules.HTML(
        f'<section class="rule-section rule-section-{kind}">'
        f'  <header class="rule-section-head">'
        f'    <span class="rule-step">{escape(step)}</span>'
        f'    <div><h4>{escape(title)}</h4>'
        f'    <p>{escape(desc)}</p></div>'
        f'  </header>'
        f'  <div class="rule-section-body">'
    )


_rule_section_close = rules.HTML('</div></section>')
_rule_sections_open = rules.HTML('<div class="rule-form-sections">')
_rule_sections_close = rules.HTML('</div>')


def _modern_rule_form(main_fields, condition_fields, outcome_fields,
                      outcome_title='Outcomes',
                      outcome_desc='What happens when the conditions match.'):
    """Return a full `form_rules` list styled as three step-cards."""
    return [
        rules.HTML(_MODERN_RULE_CSS),
        _rule_sections_open,
        _rule_section_open(
            '1', 'main', 'Main Options',
            'Name, description, activation and evaluation order.'),
        *main_fields,
        _rule_section_close,
        _rule_section_open(
            '2', 'cond', 'Conditions',
            'When does this rule apply? Match hostname or any host attribute.'),
        *condition_fields,
        _rule_section_close,
        _rule_section_open(
            '3', 'out', outcome_title, outcome_desc),
        *outcome_fields,
        _rule_section_close,
        _rule_sections_close,
    ]


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

    form_rules = _modern_rule_form(
        main_fields=[
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            div_close,
            rules.Field('sort_field'),
        ],
        condition_fields=[
            rules.Field('condition_typ'),
            rules.Field('conditions'),
        ],
        outcome_fields=[rules.Field('outcomes')],
        outcome_title='Outcomes',
        outcome_desc='What the rule does to matching hosts — e.g. set '
                     'folder, add attribute, create group.',
    )

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
       FilterLike(
            "name",
           'Name'
       ),
       BooleanEqualFilter(
            "enabled",
           'Enabled'
       )
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

    def create_model(self, form):
        """ 
        Create model
        """
        try:
            return super().create_model(form)
        except NotUniqueError:
            flash("Duplicate Entry Name", "error")
            return False

    def on_model_change(self, form, model, is_created):
        """
        Overwrite Actions on Model Change
        """
        add_changes()

        try:
            super().on_model_change(form, model, is_created)
        except NotUniqueError as exce:
            flash("Duplicate Entry Name", "error")
            raise ValueError("NotUniqueError: Object name not Unique") from exce

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

    form_rules = _modern_rule_form(
        main_fields=[
            rules.Field('name'),
            rules.Field('documentation'),
            div_open,
            rules.NestedRule(('enabled', 'last_match')),
            div_close,
            rules.Field('sort_field'),
        ],
        condition_fields=[
            rules.Field('condition_typ'),
            rules.Field('conditions'),
        ],
        outcome_fields=[rules.Field('outcomes')],
        outcome_title='Filter Actions',
        outcome_desc='Which labels / attributes pass through for matching hosts.',
    )

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
       FilterLike(
            "name",
           'Name'
       ),
       BooleanEqualFilter(
            "enabled",
           'Enabled'
       )
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

    def create_model(self, form):
        """ 
        Create model
        """
        try:
            return super().create_model(form)
        except NotUniqueError:
            flash("Duplicate Entry Name", "error")
            return False

    def on_model_change(self, form, model, is_created):
        """
        Overwrite Actions on Model Change
        """
        add_changes()

        try:
            super().on_model_change(form, model, is_created)
        except NotUniqueError as exce:
            flash("Duplicate Entry Name", "error")
            raise ValueError("NotUniqueError: Object name not Unique") from exce

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
            highlight(str(entry.new_value), DjangoLexer(), HtmlFormatter(sytle='colorfull'))

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
                {escape(attribute_name)}
                </p>
                <h6 class="card-subtitle mb-2 text-muted">To new Value</h6>
                {value}
              </div>
            </div>
            '''
    return Markup(html)


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
